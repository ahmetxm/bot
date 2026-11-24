"""Event-driven backtest of the strategy replica (pair_strategy.py) on real market tapes.

Fill model (conservative, documented in the report):
  * Maker: our resting BUY at price b on outcome i is filled by a real taker print that hits the
    bid side of i *through* our price: a taker SELL of i at x < b, or a taker BUY of the other
    outcome at y with 1-y < b (Polymarket matches complementary BUYs by minting).  Prints exactly
    AT b fill only `queue_fill_fraction` of their size (0 = we are always last in the queue).
    Fill size is capped by the print size and our remaining order size.  We fill at b.
  * Taker: an order decided at second s executes only against a real taker print in
    [s+latency, s+latency+1] on the same outcome/side at a price within our limit, for at most
    `taker_share_of_print` of that print.  Taker fee = rate * p * (1-p) per share.
  * Decisions at second s use the spot close of second s and go live at s + latency.
  * Every market is simulated independently with a fixed budget (no compounding); the daily
    loss halt is applied afterwards in chronological order (exact, because markets don't interact).
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import os
import time
import zlib
from collections import defaultdict
from multiprocessing import get_context
from pathlib import Path
from typing import Optional

import numpy as np

from common import load_config, save_json, setup_logging, utc
from fair_value import ewma_variance, fair_up_series
from market_data import SpotHistory, TapeStore, resolve_range
from pair_strategy import Inventory, PairStrategy, StrategyParams, taker_fee_per_share

log = logging.getLogger("strategy_backtest")

# globals shared with forked workers
_MARKETS: list = []
_SPOT: dict = {}
_EWVAR: dict = {}
_BT: dict = {}


# --------------------------------------------------------------------------- data
def load_universe(cfg: dict, days: Optional[float] = None) -> tuple[list, dict]:
    scfg = cfg["strategy_backtest"]
    start, end = resolve_range(cfg, days)
    store = TapeStore(cfg)
    idx = store.load_index()
    markets = []
    for m in idx.values():
        if not m.get("payouts") or not m.get("condition_id"):
            continue
        if m["window_start"] < start or m["window_end"] > end:
            continue
        if not store.tape_path(m["slug"]).exists():
            continue
        m = dict(m)
        m["category"] = f"{m['asset']} {m['timeframe']}"
        tape = [r for r in store.load_tape(m["slug"]) if m["window_start"] <= r[0] <= m["window_end"]]
        markets.append((m, tape))
    markets.sort(key=lambda x: x[0]["window_start"])
    spot = {}
    for a in sorted({m["asset"] for m, _ in markets}):
        lo = min(m["window_start"] for m, _ in markets if m["asset"] == a) - 3700
        hi = max(m["window_end"] for m, _ in markets if m["asset"] == a)
        spot[a] = SpotHistory.load(a, lo, hi, Path(cfg["paths"]["data_dir"]) / "spot")
    return markets, spot


def _fair_for(meta: dict, params: StrategyParams) -> Optional[np.ndarray]:
    sp = _SPOT.get(meta["asset"])
    ws, we, L = meta["window_start"], meta["window_end"], int(meta.get("twap_lookback") or 0)
    if sp is None or not sp.covers(ws - max(L, 1) - 10, we):
        return None
    key = (meta["asset"], params.vol_halflife_seconds)
    if key not in _EWVAR:
        _EWVAR[key] = ewma_variance(np.log(sp.closes), params.vol_halflife_seconds)
    return fair_up_series(np.log(sp.closes), _EWVAR[key], sp.t0, ws, we, ws, we, L,
                          params.vol_multiplier, params.vol_floor)


# --------------------------------------------------------------------------- simulator
def simulate_market(meta: dict, tape: list, fair: np.ndarray, params: StrategyParams,
                    bt: dict, budget: float) -> dict:
    ws, we = meta["window_start"], meta["window_end"]
    fee_rate = float(meta.get("fee_rate") or 0.0)
    tick = float(meta.get("tick") or 0.01)
    lat = int(bt.get("latency_seconds", 1))
    qfrac = float(bt.get("queue_fill_fraction", 0.0))
    tshare = float(bt.get("taker_share_of_print", 0.5))
    rebate_rate = float(bt.get("maker_rebate_rate", 0.0))
    stale = 10
    strat = PairStrategy(params, fee_rate, tick, float(meta.get("min_size") or 5), budget)
    inv = Inventory()

    # Data API timestamps trail the real CLOB match by ~1-3.4 s (measured: median 2.2 s), so prints
    # are moved earlier by `tape_timestamp_lag_seconds`; otherwise the fair value would "see" spot
    # moves that happened after the trade (look-ahead bias).
    lag_samples = bt.get("_lag_samples")
    by_sec = defaultdict(list)
    if lag_samples:   # per-print delay drawn from the measured distribution (deterministic seed)
        rng = np.random.default_rng(zlib.crc32(meta["slug"].encode()))
        d = rng.choice(np.asarray(lag_samples), size=len(tape))
        u = rng.random(len(tape))   # Data API second is truncated: true time within [ts, ts+1)
        for r, di, ui in zip(tape, d, u):
            by_sec[int(math.floor(r[0] + ui - di))].append(r)
    else:
        lag_shift = int(bt.get("tape_timestamp_lag_seconds", 3))
        for r in tape:
            by_sec[r[0] - lag_shift].append(r)
    last_ask = [(-1e9, None), (-1e9, None)]   # (ts, price) from taker BUY prints
    last_bid = [(-1e9, None), (-1e9, None)]   # from taker SELL prints
    quotes: dict = {}          # outcome -> [price, remaining]
    pending_q: list = []       # (live_from, desired dict)
    pending_t: list = []       # [live_from, expires, side, i, limit, remaining]
    max_cost = 0.0
    t_end = we - params.stop_before_end_seconds

    for s in range(ws, we + 1):
        # activate quote updates that are now live
        while pending_q and pending_q[0][0] <= s:
            _, desired = pending_q.pop(0)
            for i in (0, 1):
                if i not in desired:
                    quotes.pop(i, None)
                    continue
                price, size = desired[i]
                cur = quotes.get(i)
                if cur and abs(cur[0] - price) < params.requote_threshold - 1e-9:
                    cur[1] = max(cur[1], size)      # same price: keep the order, top it up
                    continue
                quotes[i] = [price, size]
        trades = by_sec.get(s)
        if trades:
            for (_, side, oi, px, sz) in trades:
                # ---- maker fills
                hit_i, P = (oi, px) if side == "SELL" else (1 - oi, round(1.0 - px, 6))
                q = quotes.get(hit_i)
                if q and q[1] > 1e-9:
                    if P < q[0] - 1e-9:
                        f = min(q[1], sz)
                    elif abs(P - q[0]) < 1e-9:
                        f = min(q[1], sz * qfrac)
                    else:
                        f = 0.0
                    room = (strat.budget - inv.cost_basis) / max(q[0], 0.01)
                    f = min(f, max(room, 0.0))
                    if f >= 0.01:
                        reb = rebate_rate * taker_fee_per_share(q[0], fee_rate) * f
                        inv.apply_buy(hit_i, q[0], f, 0.0, True, reb)
                        q[1] -= f
                # ---- taker fills against the same prints
                for po in pending_t:
                    if po[5] <= 1e-9 or not (po[0] <= s <= po[1]) or po[3] != oi or po[2] != side:
                        continue
                    if side == "BUY" and px <= po[4] + 1e-9:
                        room = (strat.budget - inv.cost_basis) / max(px, 0.01)
                        f = min(po[5], sz * tshare, max(room, 0.0))
                        if f >= 0.01:
                            inv.apply_buy(oi, px, f, taker_fee_per_share(px, fee_rate) * f, False)
                            po[5] -= f
                    elif side == "SELL" and px >= po[4] - 1e-9:
                        f = min(po[5], sz * tshare)
                        if f >= 0.01:
                            got = inv.apply_sell(oi, px, f, taker_fee_per_share(px, fee_rate) * f, False)
                            po[5] -= got
            for (_, side, oi, px, sz) in trades:
                if side == "BUY":
                    last_ask[oi] = (s, px)
                else:
                    last_bid[oi] = (s, px)
        pending_t = [po for po in pending_t if po[1] >= s and po[5] > 1e-9]
        max_cost = max(max_cost, inv.cost_basis)

        # ---- decision at s (live at s+lat)
        if s > t_end:
            if quotes or pending_q:
                quotes.clear(); pending_q.clear()
            continue
        if s < ws + params.start_delay_seconds:
            continue
        fu = float(fair[s - ws])
        ask = [last_ask[i][1] if s - last_ask[i][0] <= stale else None for i in (0, 1)]
        bid = [last_bid[i][1] if s - last_bid[i][0] <= stale else None for i in (0, 1)]
        for i in (0, 1):   # complementary book: ask_i <= 1 - bid_j, bid_i >= 1 - ask_j
            j = 1 - i
            if bid[j] is not None:
                ask[i] = min(ask[i], 1 - bid[j]) if ask[i] is not None else 1 - bid[j]
        for i in (0, 1):
            j = 1 - i
            if last_ask[j][1] is not None and s - last_ask[j][0] <= stale:
                imp = 1 - last_ask[j][1]
                bid[i] = max(bid[i], imp) if bid[i] is not None else imp
            if bid[i] is not None and ask[i] is not None and bid[i] >= ask[i]:
                bid[i] = None
        g = s - ws - params.guard_seconds
        desired = strat.quotes(s, ws, we, fu, inv, bid, ask, float(fair[g]) if g >= 0 else None)
        pending_q.append((s + lat, desired))
        busy = {(po[2], po[3]) for po in pending_t}
        for (side, i, limit, size) in strat.taker_orders(s, ws, we, fu, inv, bid, ask):
            if (side, i) not in busy:
                pending_t.append([s + lat, s + lat + 1, side, i, limit, size])

    payouts = meta["payouts"]
    pnl = inv.settle(payouts)
    a0, a1 = inv.avg_cost(0), inv.avg_cost(1)
    mn, mx = min(inv.shares), max(inv.shares)
    return {
        "slug": meta["slug"], "category": meta["category"], "ws": ws, "we": we,
        "pnl": pnl, "max_cost": max_cost, "buy_usdc": inv.buy_usdc, "sell_usdc": inv.sell_usdc,
        "fees": inv.fees, "rebates": inv.rebates, "maker_fills": inv.maker_fills,
        "taker_fills": inv.taker_fills, "shares": list(inv.shares),
        "pair_cost": (a0 + a1) if (a0 is not None and a1 is not None) else None,
        "two_sided": bool(inv.buy_shares[0] > 0 and inv.buy_shares[1] > 0),
        "balance": (mn / mx) if mx > 0 else None,
        "traded": inv.maker_fills + inv.taker_fills > 0,
    }


def _worker(args):
    k, pdict, budget, bt_over = args
    meta, tape = _MARKETS[k]
    params = StrategyParams(**pdict)
    if meta["category"] not in params.markets:
        return None
    fair = _fair_for(meta, params)
    if fair is None:
        return None
    bt = {**_BT, **bt_over} if bt_over else _BT
    return simulate_market(meta, tape, fair, params, bt, budget)


def run_params(pool, idxs: list, params: StrategyParams, budget: float,
               bt_over: Optional[dict] = None) -> list:
    jobs = [(k, params.as_dict(), budget, bt_over) for k in idxs]
    return [r for r in pool.map(_worker, jobs, chunksize=8) if r is not None]


# --------------------------------------------------------------------------- metrics
def summarize(results: list, start_balance: float, max_daily_loss: Optional[float]) -> dict:
    res = sorted(results, key=lambda r: r["we"])
    halted_day, day_pnl, kept, halts = None, defaultdict(float), [], 0
    halt_time: dict = {}
    for r in res:
        day = time.strftime("%Y-%m-%d", time.gmtime(r["we"]))
        if day in halt_time and r["ws"] >= halt_time[day]:
            continue
        kept.append(r)
        day_pnl[day] += r["pnl"]
        if max_daily_loss and day not in halt_time and day_pnl[day] <= -max_daily_loss:
            halt_time[day] = r["we"]
            halts += 1
    traded = [r for r in kept if r["traded"]]
    pnl = float(sum(r["pnl"] for r in kept))
    eq = start_balance + np.cumsum([r["pnl"] for r in kept]) if kept else np.array([start_balance])
    peak = np.maximum.accumulate(np.concatenate([[start_balance], eq]))
    dd = float(np.max(peak - np.concatenate([[start_balance], eq])))
    days = sorted(day_pnl)
    dvals = np.array([day_pnl[d] for d in days]) if days else np.array([0.0])
    sharpe = float(dvals.mean() / dvals.std() * math.sqrt(365)) if len(dvals) > 1 and dvals.std() > 0 else None
    # peak concurrent capital
    ev = sorted([(r["ws"], r["max_cost"]) for r in traded] + [(r["we"], -r["max_cost"]) for r in traded])
    run = peak_cap = 0.0
    for _, v in ev:
        run += v
        peak_cap = max(peak_cap, run)
    buy = float(sum(r["buy_usdc"] for r in traded))
    pcs = [r["pair_cost"] for r in traded if r["pair_cost"] is not None]
    bals = [r["balance"] for r in traded if r["balance"] is not None]
    by_cat = defaultdict(lambda: {"markets": 0, "pnl": 0.0, "wins": 0, "buy_usdc": 0.0})
    for r in traded:
        c = by_cat[r["category"]]
        c["markets"] += 1; c["pnl"] += r["pnl"]; c["wins"] += r["pnl"] > 0; c["buy_usdc"] += r["buy_usdc"]
    for c in by_cat.values():
        c["win_rate_pct"] = 100.0 * c["wins"] / c["markets"] if c["markets"] else 0.0
        c["roi_on_buys_pct"] = 100.0 * c["pnl"] / c["buy_usdc"] if c["buy_usdc"] else 0.0
    return {
        "markets_considered": len(res), "markets_traded": len(traded), "pnl": pnl,
        "roi_pct": 100.0 * pnl / start_balance, "final_equity": start_balance + pnl,
        "win_rate_pct": 100.0 * sum(r["pnl"] > 0 for r in traded) / len(traded) if traded else 0.0,
        "buy_usdc": buy, "roi_on_buys_pct": 100.0 * pnl / buy if buy else 0.0,
        "fees": float(sum(r["fees"] for r in traded)), "rebates": float(sum(r["rebates"] for r in traded)),
        "maker_fills": int(sum(r["maker_fills"] for r in traded)),
        "taker_fills": int(sum(r["taker_fills"] for r in traded)),
        "max_drawdown": dd, "sharpe_daily_annualized": sharpe, "daily_pnl": {d: day_pnl[d] for d in days},
        "daily_loss_halts": halts, "peak_concurrent_capital": peak_cap,
        "median_pair_cost": float(np.median(pcs)) if pcs else None,
        "two_sided_pct": 100.0 * sum(r["two_sided"] for r in traded) / len(traded) if traded else 0.0,
        "median_balance": float(np.median(bals)) if bals else None,
        "by_category": dict(by_cat),
        "equity_curve": [[r["we"], float(e)] for r, e in zip(kept, eq)],
    }


# --------------------------------------------------------------------------- calibration
def calibrate_vol(markets: list, idxs: list, base: StrategyParams) -> dict:
    """Log-loss of the fair value vs. actual outcomes (sampled every 30 s) for several multipliers,
    compared with the market's own last traded price."""
    out = {}
    for vm in (0.8, 1.0, 1.25, 1.5, 2.0):
        p = StrategyParams(**{**base.as_dict(), "vol_multiplier": vm})
        ll, n = 0.0, 0
        for k in idxs:
            meta, _ = markets[k]
            fair = _fair_for(meta, p)
            if fair is None:
                continue
            y = 1.0 if meta["payouts"][0] == 1.0 else 0.0
            for s in range(30, len(fair) - 1, 30):
                f = min(max(fair[s], 1e-3), 1 - 1e-3)
                ll -= y * math.log(f) + (1 - y) * math.log(1 - f)
                n += 1
        out[vm] = ll / max(n, 1)
    # market benchmark: last Up-equivalent print before each sample second
    ll, n = 0.0, 0
    for k in idxs:
        meta, tape = markets[k]
        y = 1.0 if meta["payouts"][0] == 1.0 else 0.0
        ws, we = meta["window_start"], meta["window_end"]
        j, last = 0, None
        for s in range(ws + 30, we, 30):
            while j < len(tape) and tape[j][0] <= s:
                _, side, oi, px, _ = tape[j]
                last = px if oi == 0 else 1 - px
                j += 1
            if last is None:
                continue
            f = min(max(last, 1e-3), 1 - 1e-3)
            ll -= y * math.log(f) + (1 - y) * math.log(1 - f)
            n += 1
    out["market_last_print"] = ll / max(n, 1)
    return out


def main(argv: Optional[list[str]] = None) -> dict:
    global _MARKETS, _SPOT, _BT
    ap = argparse.ArgumentParser(description="Calibrate + backtest the strategy replica")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--no-grid", action="store_true", help="only evaluate config parameters")
    ap.add_argument("--select-delay", choices=("measured", "fixed3"), default="measured",
                    help="tape delay used to SELECT parameters on train (fixed3 = no look-ahead, conservative)")
    ap.add_argument("--grid", choices=("v1", "v2"), default="v1", help="v2 adds taker-edge levels and cut-offs")
    ap.add_argument("--tag", default="", help="suffix for output files (keeps the main results untouched)")
    args = ap.parse_args(argv)
    sel_over = ({"_lag_samples": None, "tape_timestamp_lag_seconds": 3} if args.select_delay == "fixed3" else None)
    sfx = f"_{args.tag}" if args.tag else ""
    cfg = load_config()
    setup_logging(cfg, "strategy_backtest")
    _BT = dict(cfg["strategy_backtest"])
    lag_file = Path(cfg["paths"]["data_dir"]) / "tape_lag_measurement.json"
    if lag_file.exists() and _BT.get("use_measured_lag", True):
        meas = json.loads(lag_file.read_text())
        # Data API seconds are truncated, so up to -1 s is physical; anything earlier is a WS/API mismatch
        samples = [x for x in (meas.get("lag_samples") or []) if x >= -1.0]
        if len(samples) >= 30:
            _BT["_lag_samples"] = samples
            log.info("tape timestamp lag: %d measured samples (median %.2f s)",
                     len(samples), float(np.median(samples)))
    t_start = time.time()
    _MARKETS, _SPOT = load_universe(cfg, args.days)
    if not _MARKETS:
        raise SystemExit("no markets with tapes - run `python main.py fetch-tapes` first")
    n = len(_MARKETS)
    split = int(n * float(_BT.get("train_fraction", 0.6)))
    train, test = list(range(split)), list(range(split, n))
    m0, m1 = _MARKETS[0][0], _MARKETS[-1][0]
    log.info("%d markets %s -> %s | train %d (until %s) | test %d", n, utc(m0["window_start"]),
             utc(m1["window_end"]), len(train), utc(_MARKETS[split - 1][0]["window_end"]), len(test))
    start_balance = float(cfg["paper_trading"]["starting_balance"])
    budget = min(float(cfg["risk"]["max_position_pct"]) * start_balance,
                 float(cfg["pair_strategy"]["max_market_usd"]))
    max_daily_loss = float(cfg["risk"]["max_daily_loss"])
    base = StrategyParams.from_cfg(cfg, {"markets": ["BTC 5m", "BTC 15m", "ETH 5m", "ETH 15m"]})

    # 1) volatility multiplier: pure forecasting accuracy on the training markets
    vol_ll = calibrate_vol(_MARKETS, train[:: max(1, len(train) // 600)], base)
    best_vm = min((k for k in vol_ll if k != "market_last_print"), key=lambda k: vol_ll[k])
    log.info("fair-value log-loss by vol multiplier: %s -> %.2f",
             {k: round(v, 4) for k, v in vol_ll.items()}, best_vm)
    base = StrategyParams(**{**base.as_dict(), "vol_multiplier": best_vm})

    ctx = get_context("fork")
    grid_rows = []
    with ctx.Pool(min(30, os.cpu_count() or 4)) as pool:
        cfg_params = StrategyParams(**{**base.as_dict()})
        if args.no_grid:
            candidates = [cfg_params.as_dict()]
        elif args.grid == "v2":
            candidates = []
            for hs, te, gm, tc in itertools.product([0.03, 0.05, 0.08, None],   # half_spread (None = no maker)
                                                    [None, 0.03, 0.05, 0.08],   # take_edge (None = no taker)
                                                    [0.0, 0.02],                # adverse-move guard
                                                    [1.0, 0.75]):               # taker cut-off (window fraction)
                if hs is None and te is None:
                    continue
                if te is None and tc != 1.0:
                    continue
                d = base.as_dict()
                d.update(half_spread=hs if hs is not None else 1.0, take_enabled=te is not None,
                         take_edge=te or 0.0, guard_move=gm, take_cutoff_frac=tc, inventory_skew=0.02,
                         max_imbalance_shares=150, order_shares=25, take_shares=25)
                candidates.append(d)
        else:
            grid = itertools.product([0.02, 0.03, 0.05, 0.08],          # half_spread
                                     [None, 0.04],                       # take_edge (None = off)
                                     [0.0, 0.02],                        # adverse-move guard
                                     [(0.02, 150), (0.05, 60)],          # (inventory_skew, max_imbalance)
                                     [10, 25])                           # order_shares
            candidates = []
            for hs, te, gm, (sk, mi), osz in grid:
                d = base.as_dict()
                d.update(half_spread=hs, take_enabled=te is not None, take_edge=te or 0.0, guard_move=gm,
                         inventory_skew=sk, max_imbalance_shares=mi, order_shares=osz, take_shares=osz)
                candidates.append(d)
        log.info("grid: %d parameter sets on %d training markets", len(candidates), len(train))
        for d in candidates:
            p = StrategyParams(**d)
            res = run_params(pool, train, p, budget, sel_over)
            sm = summarize(res, start_balance, None)
            row = {k: d[k] for k in ("half_spread", "take_enabled", "take_edge", "guard_move",
                                     "inventory_skew", "max_imbalance_shares", "order_shares", "take_cutoff_frac")}
            row.update(pnl=sm["pnl"], roi_on_buys_pct=sm["roi_on_buys_pct"], markets=sm["markets_traded"],
                       buy_usdc=sm["buy_usdc"], by_category={c: v["pnl"] for c, v in sm["by_category"].items()})
            grid_rows.append((row, d))
            log.info("  hs=%.2f take=%s guard=%.2f skew=%.2f imb=%d sz=%d -> train PnL %+.0f (ROI/buys %.2f%%, %d mkts)",
                     d["half_spread"], d["take_edge"] if d["take_enabled"] else "off", d["guard_move"], d["inventory_skew"],
                     d["max_imbalance_shares"], d["order_shares"], sm["pnl"], sm["roi_on_buys_pct"],
                     sm["markets_traded"])
        best_row, best = max(grid_rows, key=lambda x: x[0]["pnl"])
        # 2) market selection on TRAIN only: keep categories that made money with the best params
        cats = [c for c, v in best_row["by_category"].items() if v > 0]
        chosen = StrategyParams(**{**best, "markets": cats or best["markets"]})
        log.info("chosen params (train): %s", {k: v for k, v in chosen.as_dict().items()
                                               if k in ("markets", "half_spread", "take_enabled", "take_edge",
                                                        "guard_move", "inventory_skew", "max_imbalance_shares",
                                                        "order_shares")})
        train_sum = summarize(run_params(pool, train, chosen, budget, sel_over), start_balance, max_daily_loss)
        test_res = run_params(pool, test, chosen, budget, sel_over)
        test_sum = summarize(test_res, start_balance, max_daily_loss)
        test_all_cats = summarize(run_params(pool, test, StrategyParams(**best), budget, sel_over),
                                  start_balance, max_daily_loss)
        cfg_default = summarize(run_params(pool, test, StrategyParams.from_cfg(
            cfg, {"vol_multiplier": best_vm}), budget, sel_over), start_balance, max_daily_loss)
        # 3) robustness: the edge depends on how late the Data API timestamps really are. A fixed
        #    shift >= the true delay removes all look-ahead (pessimistic for maker quotes, which in
        #    reality use fresher spot data); a random draw from the measured delays can be optimistic
        #    because the strategy selectively trades prints whose drawn delay was too small.
        robustness = {}
        no_take = StrategyParams(**{**chosen.as_dict(), "take_enabled": False})
        for name, over in (("measured random delay (main result)", {}),
                           ("fixed 2 s delay", {"_lag_samples": None, "tape_timestamp_lag_seconds": 2}),
                           ("fixed 3 s delay (no look-ahead)", {"_lag_samples": None, "tape_timestamp_lag_seconds": 3}),
                           ("fixed 3 s delay + 2 s latency", {"_lag_samples": None, "tape_timestamp_lag_seconds": 3,
                                                              "latency_seconds": 2})):
            robustness[name] = {
                "chosen": summarize(run_params(pool, test, chosen, budget, over), start_balance, max_daily_loss),
                "maker_only": summarize(run_params(pool, test, no_take, budget, over), start_balance, max_daily_loss)}
            log.info("robustness %-38s test PnL chosen %+.0f | maker-only %+.0f", name,
                     robustness[name]["chosen"]["pnl"], robustness[name]["maker_only"]["pnl"])

    out = {
        "generated_at": utc(time.time()),
        "data": {"markets": n, "train_markets": len(train), "test_markets": len(test),
                 "from": utc(m0["window_start"]), "to": utc(m1["window_end"]),
                 "train_until": utc(_MARKETS[split - 1][0]["window_end"])},
        "assumptions": {**{k: _BT.get(k) for k in ("queue_fill_fraction", "taker_share_of_print",
                                                   "latency_seconds", "maker_rebate_rate")},
                        "tape_timestamp_lag": (f"measured distribution, {len(_BT['_lag_samples'])} samples"
                                               if _BT.get("_lag_samples") else
                                               f"fixed {_BT.get('tape_timestamp_lag_seconds', 3)} s")},
        "budget_per_market": budget, "starting_balance": start_balance,
        "fair_value_logloss": vol_ll, "chosen_params": chosen.as_dict(),
        "grid": [r for r, _ in grid_rows],
        "train": train_sum, "test": test_sum,
        "test_all_categories_best_params": test_all_cats,
        "test_config_defaults": cfg_default,
        "robustness_test": {k: {kk: {x: vv[x] for x in ("pnl", "roi_on_buys_pct", "win_rate_pct", "markets_traded",
                                                       "maker_fills", "taker_fills", "fees", "max_drawdown")}
                                for kk, vv in v.items()} for k, v in robustness.items()},
        "runtime_seconds": round(time.time() - t_start, 1),
    }
    out["selection_delay"] = args.select_delay
    out["grid_version"] = args.grid
    rep = Path(cfg["paths"]["reports_dir"])
    save_json(out, rep / f"strategy_backtest{sfx}.json")
    save_json({"params": chosen.as_dict(), "calibrated_at": out["generated_at"],
               "train_window": [out["data"]["from"], out["data"]["train_until"]],
               "selection_delay": args.select_delay, "test_pnl": test_sum["pnl"]},
              Path(cfg["paths"]["data_dir"]) / f"calibrated_params{sfx}.json")
    save_json(test_res, rep / f"strategy_backtest_test_markets{sfx}.json")
    write_report(out, rep, sfx)
    log.info("TEST (out-of-sample): PnL %+.2f | ROI %.2f%% | win %.1f%% | markets %d | maxDD %.0f",
             test_sum["pnl"], test_sum["roi_pct"], test_sum["win_rate_pct"], test_sum["markets_traded"],
             test_sum["max_drawdown"])
    return out


def write_report(out: dict, rep: Path, sfx: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    (rep / "charts").mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for key, label in (("train", "train (calibration)"), ("test", "test (out-of-sample)")):
        ec = out[key]["equity_curve"]
        if ec:
            ax.plot([time.strftime("%m-%d %H:%M", time.gmtime(t)) for t, _ in ec][::max(1, len(ec) // 400)],
                    [e for _, e in ec][::max(1, len(ec) // 400)], label=label)
    ax.set_title("Strategy replica - equity (fixed $%.0f budget per market)" % out["budget_per_market"])
    ax.set_ylabel("USDC"); ax.legend(); ax.grid(alpha=.3)
    ax.set_xticks(ax.get_xticks()[:: max(1, len(ax.get_xticks()) // 8)])
    plt.xticks(rotation=30, fontsize=7); plt.tight_layout()
    fig.savefig(rep / "charts" / f"strategy_equity{sfx}.png", dpi=110); plt.close(fig)

    def row(name, s):
        sh = s["sharpe_daily_annualized"]
        return (f"| {name} | {s['markets_traded']} | ${s['pnl']:,.2f} | {s['roi_pct']:.2f}% | "
                f"{s['win_rate_pct']:.1f}% | {s['roi_on_buys_pct']:.2f}% | ${s['max_drawdown']:,.0f} | "
                f"{'n/a' if sh is None else f'{sh:.1f}'} | {s['maker_fills']}/{s['taker_fills']} | "
                f"${s['fees']:,.2f} |")

    cp = out["chosen_params"]
    L = [
        "# Strategy replica backtest", "",
        f"Generated {out['generated_at']}. Data: {out['data']['markets']} resolved crypto Up/Down markets "
        f"{out['data']['from']} -> {out['data']['to']}; calibration on the first {out['data']['train_markets']} "
        f"(until {out['data']['train_until']}), out-of-sample test on the last {out['data']['test_markets']}.", "",
        f"Starting balance ${out['starting_balance']:,.0f}, budget per market ${out['budget_per_market']:,.0f}, "
        f"daily loss halt applied. Fill assumptions: {out['assumptions']}.", "",
        f"Parameter selection and train/test rows use tape delay model: **{out.get('selection_delay', 'measured')}** "
        f"(fixed3 = every print shifted 3 s earlier, no look-ahead). Grid: {out.get('grid_version', 'v1')}.", "",
        "## Results", "",
        "| run | markets | PnL | ROI | win rate | PnL / buys | max DD | Sharpe | maker/taker fills | fees |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        row("train (in-sample, chosen params)", out["train"]),
        row("**test (out-of-sample, chosen params)**", out["test"]),
        row("test - best params, all categories", out["test_all_categories_best_params"]),
        row("test - config.yaml defaults", out["test_config_defaults"]), "",
        "Target wallet reference (Mar 2026, 7 days): PnL / buys 1.71%, win rate 50.6%, median pair cost 0.918, "
        "two-sided 93.9%, 78% maker fills.", "",
        f"Replica behaviour (test): median pair cost {out['test']['median_pair_cost']}, two-sided "
        f"{out['test']['two_sided_pct']:.1f}%, median balance {out['test']['median_balance']}.", "",
        "## Chosen parameters", "", "```json", json.dumps(cp, indent=1), "```", "",
        "## Fair-value accuracy (log-loss, lower is better)", "",
        "| model | log-loss |", "|---|---:|",
    ] + [f"| {k} | {v:.4f} |" for k, v in out["fair_value_logloss"].items()] + [
        "", "## Robustness (test period): how late are the trade timestamps?", "",
        "The Data API stamps trades ~1-3.5 s after the real match (measured live). The result depends heavily "
        "on this delay: a fixed 3 s shift removes all look-ahead but is pessimistic for maker quotes; the random "
        "measured delay can be optimistic. **Treat the backtest as inconclusive unless both are positive.**", "",
        "| delay model | chosen params PnL | PnL / buys | maker-only PnL | PnL / buys |", "|---|---:|---:|---:|---:|",
    ] + [f"| {k} | ${v['chosen']['pnl']:,.0f} | {v['chosen']['roi_on_buys_pct']:.2f}% | ${v['maker_only']['pnl']:,.0f} | "
         f"{v['maker_only']['roi_on_buys_pct']:.2f}% |" for k, v in out["robustness_test"].items()] + [
        "", "## Test by category", "", "| category | markets | PnL | win rate | PnL / buys |", "|---|---:|---:|---:|---:|",
    ] + [f"| {c} | {v['markets']} | ${v['pnl']:,.2f} | {v['win_rate_pct']:.1f}% | {v['roi_on_buys_pct']:.2f}% |"
         for c, v in sorted(out["test_all_categories_best_params"]["by_category"].items())] + [
        "", "## Daily PnL (test)", "", "| day | PnL |", "|---|---:|",
    ] + [f"| {d} | ${v:,.2f} |" for d, v in out["test"]["daily_pnl"].items()] + [
        "", f"Chart: `charts/strategy_equity{sfx}.png`. Grid results: `strategy_backtest{sfx}.json`.",
    ]
    (rep / f"strategy_backtest{sfx}.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
