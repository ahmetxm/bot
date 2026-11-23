#!/usr/bin/env python3
"""End-to-end test: collect (if needed) -> analyse -> backtest -> performance report.

Backtest scenarios (all replay the target's real fills chronologically through CopyEngine + PaperTrader):
  target_replica        the target itself (ratio 1, no limits/fees) - validates the replay against
                        Polymarket's own PnL numbers and measures the capital the target deployed
  ideal_copy            our $10k account, proportional sizing, every fill copied instantly at the
                        target's own price, no fees/slippage (theoretical upper bound)
  realistic_copy        what the live bot can actually do: fills batched per 10 s poll, +2 s order
                        latency, priced at the next market print after execution, +30 bps slippage,
                        Polymarket taker fees, min order size, all risk limits
  realistic_taker_only  as realistic_copy but only the target's aggressive (taker) fills are copied

Usage:  python run_test.py [--refresh] [--days 7]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from bot import CopyEngine  # noqa: E402
from common import load_config, load_json, save_json, setup_logging, utc  # noqa: E402
from data_collector import DataCollector, load_collected  # noqa: E402
from paper_trader import PaperTrader  # noqa: E402
from strategy_analyzer import StrategyAnalyzer, prepare_trades  # noqa: E402

SCENARIO_DEFS = {
    "target_replica": dict(poll=0, latency=0, price_mode="fill", fees=False, limits=False, taker_only=False,
                           fixed_ratio=1.0, slippage=False),
    "ideal_copy": dict(poll=0, latency=0, price_mode="fill", fees=False, limits=True, taker_only=False,
                       fixed_ratio=None, slippage=False),
    "realistic_copy": dict(poll=None, latency=None, price_mode="next_print", fees=True, limits=True,
                           taker_only=False, fixed_ratio=None, slippage=True),
    "realistic_taker_only": dict(poll=None, latency=None, price_mode="next_print", fees=True, limits=True,
                                 taker_only=True, fixed_ratio=None, slippage=True),
    # diagnostics: isolate where the edge goes
    "diag_fill_price_with_fees": dict(poll=0, latency=0, price_mode="fill", fees=True, limits=True,
                                      taker_only=False, fixed_ratio=None, slippage=False),
    "diag_realistic_no_loss_halt": dict(poll=None, latency=None, price_mode="next_print", fees=True, limits=True,
                                        taker_only=False, fixed_ratio=None, slippage=True,
                                        risk_override={"max_daily_loss": float("inf")}),
}


class PriceIndex:
    """Next observed market print per market (outcome-0 price; outcome 1 = 1 - p)."""

    def __init__(self, df: pd.DataFrame, codes: np.ndarray):
        p0 = np.where(df["outcome_index"].to_numpy() == 0, df["price"].to_numpy(), 1.0 - df["price"].to_numpy())
        ts = df["timestamp"].to_numpy(dtype=float)
        order = np.lexsort((ts, codes))
        codes_s, ts_s, p_s = codes[order], ts[order], p0[order]
        bounds = np.flatnonzero(np.diff(codes_s)) + 1
        starts = np.concatenate([[0], bounds])
        ends = np.concatenate([bounds, [len(codes_s)]])
        self.series = {int(codes_s[a]): (ts_s[a:b], p_s[a:b]) for a, b in zip(starts, ends)}

    def next_price(self, code: int, outcome: int, t: float, t_max: float):
        s = self.series.get(code)
        if s is None:
            return None
        j = int(np.searchsorted(s[0], t, side="left"))
        if j < len(s[0]) and s[0][j] <= t_max:
            return float(s[1][j]) if outcome == 0 else 1.0 - float(s[1][j])
        return None


def simulate(name: str, spec: dict, df: pd.DataFrame, markets: dict, cfg: dict, codes_map: dict,
             price_index: PriceIndex, target_capital: float, log) -> tuple[PaperTrader, CopyEngine]:
    bt = cfg["backtest"]
    poll = bt["poll_interval_seconds"] if spec["poll"] is None else spec["poll"]
    latency = bt["execution_latency_seconds"] if spec["latency"] is None else spec["latency"]
    slip = bt["slippage_bps"] / 1e4 if spec["slippage"] else 0.0
    fb_slip = bt["fallback_slippage_bps"] / 1e4
    stale = float(bt["max_price_staleness_seconds"])
    start_bal = 0.0 if spec["fixed_ratio"] else float(cfg["paper_trading"]["starting_balance"])
    risk = {**cfg["risk"], **spec.get("risk_override", {})}
    trader = PaperTrader(start_bal, risk, cfg["fees"], name=name, enforce_limits=spec["limits"],
                         apply_fees=spec["fees"], logger=log)
    engine = CopyEngine(target_capital, risk["min_order_shares"] if spec["limits"] else 0.0,
                        risk["min_order_usd"] if spec["limits"] else 0.0, fixed_ratio=spec["fixed_ratio"])

    sub = df[df["role"] == "taker"] if spec["taker_only"] else df
    ts = sub["timestamp"].to_numpy(dtype=float)
    codes = sub["condition_id"].map(codes_map).to_numpy()
    idx = sub["outcome_index"].to_numpy(dtype=int)
    side = sub["side"].to_numpy()
    size = sub["size"].to_numpy(dtype=float)
    price = sub["price"].to_numpy(dtype=float)
    n = len(sub)
    if poll > 0:
        bucket = (ts // poll).astype(np.int64)
        exec_ts = (bucket + 1) * poll + latency
    else:
        bucket = np.arange(n, dtype=np.int64)
        exec_ts = ts + latency
    order = np.lexsort((np.arange(n), codes, bucket))
    b_s, c_s = bucket[order], codes[order]
    brk = np.flatnonzero((np.diff(b_s) != 0) | (np.diff(c_s) != 0)) + 1
    g_start = np.concatenate([[0], brk])
    g_end = np.concatenate([brk, [n]])

    cids = {v: k for k, v in codes_map.items()}
    meta_of, end_of = {}, {}
    res_events = []
    for code in np.unique(codes):
        cid = cids[int(code)]
        m = markets[cid]
        meta_of[int(code)] = {"title": m.get("title", ""), "category": m.get("category", ""), "slug": m.get("slug")}
        end_of[int(code)] = m.get("trade_end_ts") or np.inf
        if m.get("payouts"):
            rts = m.get("resolved_at") or ((m.get("trade_end_ts") or 0) + 300)
            res_events.append((float(rts), int(code)))
    res_events.sort()
    ri = 0
    next_snap = (float(ts.min()) // 3600 + 1) * 3600 if n else 0
    trader.snapshot(float(ts.min()) if n else 0)
    eq_fn = trader.equity
    stats = engine.stats

    for a, b in zip(g_start, g_end):
        rows = order[a:b]
        t_exec = float(exec_ts[rows[0]])
        while ri < len(res_events) and res_events[ri][0] <= t_exec:
            rt, rc = res_events[ri]
            if trader.resolve(rt, cids[rc], markets[cids[rc]]["payouts"]) is not None:
                trader.snapshot(rt)
            engine.forget(cids[rc])
            ri += 1
        while t_exec >= next_snap:
            trader.snapshot(next_snap)
            next_snap += 3600
        code = int(c_s[a])
        cid = cids[code]
        fills = [(int(idx[r]), side[r], float(size[r]), float(price[r])) for r in rows]
        if cid not in engine.ratio:
            intents = engine.process(cid, fills, eq_fn())
        else:
            intents = engine.process(cid, fills, 0.0)
        if not intents:
            continue
        meta = meta_of[code]
        closed = t_exec >= end_of[code]
        for it in intents:
            if closed:
                stats["skipped_market_closed"] += 1
                if it.side == "BUY":
                    continue
            if spec["price_mode"] == "fill":
                px = it.ref_price
            else:
                px = price_index.next_price(code, it.outcome_index, t_exec, min(t_exec + stale, end_of[code]))
                if px is None:
                    stats["fallback_price"] += 1
                    px = it.ref_price * (1 + fb_slip if it.side == "BUY" else 1 - fb_slip)
                px = px * (1 + slip) if it.side == "BUY" else px * (1 - slip)
            px = min(max(px, 0.001), 0.999)
            if closed:   # cannot trade after the close: hold to resolution
                continue
            engine.execute(trader, it, t_exec, px, meta)
            trader.mark(t_exec, cid, it.outcome_index, px)

    while ri < len(res_events):
        rt, rc = res_events[ri]
        if trader.resolve(rt, cids[rc], markets[cids[rc]]["payouts"]) is not None:
            trader.snapshot(rt)
        ri += 1
    trader.snapshot(res_events[-1][0] if res_events else float(ts.max()))
    return trader, engine


def plot_equity(results: dict, path: Path, replica_capital: float) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.5))
    for name, tr in results.items():
        e = tr.equity_frame()
        if e.empty:
            continue
        if name == "target_replica":
            ax[1].plot(e["time"], e["equity"] - replica_capital, color="#111827")
        else:
            ax[0].plot(e["time"], e["equity"], label=name)
    ax[0].axhline(results["ideal_copy"].starting_balance if "ideal_copy" in results else 0, color="grey", lw=.8, ls="--")
    ax[0].set_title("Copy-bot equity (paper, USDC)")
    ax[0].legend()
    ax[0].tick_params(axis="x", rotation=30)
    ax[1].set_title("Target wallet replay: cumulative PnL (USDC)")
    ax[1].tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def run_backtest(cfg: dict) -> dict:
    log = setup_logging(cfg, "backtest")
    reports = Path(cfg["paths"]["reports_dir"])
    bt = cfg["backtest"]
    raw, markets, meta = load_collected(cfg)
    df = prepare_trades(raw, markets)
    df = df[~df["post_close"] & df["outcome_index"].isin([0, 1])]
    end = float(df["timestamp"].max())
    data_start = float(df["timestamp"].min())
    bt_start = max(end - float(bt["days"]) * 86400, data_start + float(cfg["strategy"]["truncation_buffer_seconds"]))
    first = df.groupby("condition_id")["timestamp"].min()
    keep = set(first[first >= bt_start].index) & {c for c, m in markets.items() if m.get("payouts")}
    win = df[df["condition_id"].isin(keep)].reset_index(drop=True)
    log.info("Backtest window %s -> %s | %d fills | %d markets (markets opened before the window start "
             "are skipped, as a freshly started bot would)", utc(bt_start), utc(end), len(win), len(keep))

    codes_map = {c: i for i, c in enumerate(sorted(keep))}
    pidx = PriceIndex(win, win["condition_id"].map(codes_map).to_numpy())

    results, engines, metrics = {}, {}, {}
    scen = [s for s in bt.get("scenarios", list(SCENARIO_DEFS)) if s in SCENARIO_DEFS]
    if "target_replica" not in scen:
        scen.insert(0, "target_replica")
    target_capital = None
    manual = cfg["sizing"].get("target_capital_usd")
    for name in scen:
        t0 = time.time()
        cap = target_capital or 1.0
        tr, eng = simulate(name, SCENARIO_DEFS[name], win, markets, cfg, codes_map, pidx, cap, log)
        if name == "target_replica":
            target_capital = float(manual) if isinstance(manual, (int, float)) else tr.peak_open_cost
            # express the replay on the capital it actually needed
            tr.starting_balance = target_capital
            tr.cash += target_capital
            tr.min_cash += target_capital
            tr.equity_curve = [(t, e + target_capital, c + target_capital, k) for t, e, c, k in tr.equity_curve]
            log.info("Target capital estimate (peak concurrent cost basis): $%,.0f".replace(",", ""), target_capital)
        m = tr.save(reports, f"backtest_{name}")
        m["engine_stats"] = dict(eng.stats)
        m["runtime_seconds"] = round(time.time() - t0, 1)
        save_json(m, reports / f"backtest_{name}_metrics.json")
        results[name], engines[name], metrics[name] = tr, eng, m
        log.info("[%s] PnL %.2f (%.2f%%) | win rate %s%% | orders %d | maxDD %.2f%% | %.1fs", name, m["total_pnl"],
                 m["return_pct"] or 0, m.get("win_rate_pct"), m["n_orders"], m["max_drawdown_pct"], m["runtime_seconds"])

    plot_equity(results, reports / "charts" / "backtest_equity.png", target_capital)
    profile = load_json(Path(cfg["paths"]["data_dir"]) / "target_profile.json", {})
    gt = {}
    pts = [p for p in profile.get("pnl_hourly", []) if bt_start - 3600 <= p["timestamp"] <= end + 3600]
    if len(pts) >= 2:
        # NB: "fees" in the PnL series is gross fees before refunds; "fees_paid" is what was actually paid
        gt = {k: (pts[-1].get(k) or 0) - (pts[0].get(k) or 0) for k in ("economic_pnl", "trade_pnl", "fees_paid",
                                                                         "maker_rebate", "volume_usdc")}
        gt["fees_paid"] = abs(gt["fees_paid"])
        gt.update({"from_utc": utc(pts[0]["timestamp"]), "to_utc": utc(pts[-1]["timestamp"])})
    report = {"generated_at_utc": utc(time.time()), "wallet": cfg["target"]["wallet"],
              "window": {"start_utc": utc(bt_start), "end_utc": utc(end), "days": round((end - bt_start) / 86400, 2),
                         "fills": int(len(win)), "markets": len(keep),
                         "wallet_days_inactive": meta.get("days_inactive")},
              "assumptions": {"starting_balance": cfg["paper_trading"]["starting_balance"],
                              "target_capital_usd": round(target_capital, 2),
                              "copy_ratio_at_start": round(cfg["paper_trading"]["starting_balance"] / target_capital, 6),
                              "poll_interval_seconds": bt["poll_interval_seconds"],
                              "execution_latency_seconds": bt["execution_latency_seconds"],
                              "slippage_bps": bt["slippage_bps"], "fees": cfg["fees"], "risk": cfg["risk"]},
              "target_ground_truth_window": gt,
              "scenarios": metrics}
    report["verdict"] = verdict(report)
    save_json(report, reports / "performance_report.json")
    write_markdown(report, reports / "backtest_report.md")
    print_report(report)
    return report


def verdict(r: dict) -> list[str]:
    s = r["scenarios"]
    out = []
    rep, ideal, real = s.get("target_replica", {}), s.get("ideal_copy", {}), s.get("realistic_copy", {})
    gt = r.get("target_ground_truth_window", {})
    if rep and gt:
        out.append(f"Replay check: target PnL replayed from fills ${rep['total_pnl']:,.0f} vs Polymarket trade PnL "
                   f"${gt.get('trade_pnl', 0):,.0f} / economic PnL ${gt.get('economic_pnl', 0):,.0f} in the same window.")
    if rep:
        out.append(f"Target return on its deployed capital (${r['assumptions']['target_capital_usd']:,.0f}): "
                   f"{rep['return_pct']:.2f}% in {r['window']['days']} days.")
    if ideal:
        out.append(f"Ideal copy (instant, same price, no fees): {ideal['return_pct']:.2f}% "
                   f"(PnL ${ideal['total_pnl']:,.2f}).")
    if real:
        out.append(f"Realistic copy (10 s polling, latency, slippage, taker fees): {real['return_pct']:.2f}% "
                   f"(PnL ${real['total_pnl']:,.2f}, fees ${real['fees_paid']:,.2f}).")
        if ideal and real["total_pnl"] < ideal["total_pnl"]:
            out.append("The gap between ideal and realistic copy is the edge lost to latency, slippage and fees: "
                       "the target earns mostly as a MAKER and at sub-second speed, which a 10-second polling "
                       "follower using taker orders cannot reproduce.")
    tk = s.get("realistic_taker_only")
    if tk:
        out.append(f"Copying only the target's taker fills: {tk['return_pct']:.2f}% (PnL ${tk['total_pnl']:,.2f}).")
    fw = s.get("diag_fill_price_with_fees")
    if fw:
        out.append(f"Diagnostic - target's own prices but paying taker fees: {fw['return_pct']:.2f}% "
                   f"(fees ${fw['fees_paid']:,.2f}) -> isolates the cost of fees alone.")
    nh = s.get("diag_realistic_no_loss_halt")
    if nh and real:
        out.append(f"Diagnostic - realistic copy WITHOUT the ${r['assumptions']['risk']['max_daily_loss']:,.0f} daily-loss "
                   f"halt: {nh['return_pct']:.2f}% (PnL ${nh['total_pnl']:,.2f}); the halt fired on "
                   f"{len(real['halted_days'])} of {len(real.get('daily_realized_pnl', {}))} days in realistic_copy.")
    if (r["window"].get("wallet_days_inactive") or 0) > 2:
        out.append(f"The target wallet has been inactive for {r['window']['wallet_days_inactive']} days, so a live "
                   f"copy bot started today would receive no trades to copy.")
    return out


def write_markdown(r: dict, path: Path) -> None:
    w, a = r["window"], r["assumptions"]
    lines = ["# Backtest report - Polymarket copy-trade bot (paper trading)", "",
             f"Target `{r['wallet']}` | window {w['start_utc']} -> {w['end_utc']} ({w['days']} days) | "
             f"{w['fills']:,} target fills in {w['markets']:,} markets", "",
             f"Starting balance ${a['starting_balance']:,.0f} | target capital estimate ${a['target_capital_usd']:,.0f} "
             f"| copy ratio {a['copy_ratio_at_start']:.4f} | poll {a['poll_interval_seconds']} s + "
             f"{a['execution_latency_seconds']} s latency | slippage {a['slippage_bps']} bps", "",
             "| scenario | final equity | PnL | return % | win rate % | orders | fees | Sharpe (hourly, ann.) | max DD % | halted days |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in r["scenarios"].items():
        sh = m.get("sharpe_hourly_annualized")
        lines.append(f"| {name} | ${m['final_equity']:,.2f} | ${m['total_pnl']:,.2f} | {m['return_pct']:.2f} | "
                     f"{m.get('win_rate_pct', 0):.2f} | {m['n_orders']:,} | ${m['fees_paid']:,.2f} | "
                     f"{sh if sh is not None else '-'} | {m['max_drawdown_pct']:.2f} | {len(m['halted_days'])} |")
    gt = r.get("target_ground_truth_window") or {}
    if gt:
        lines += ["", f"Polymarket ground truth for the target in this window: trade PnL ${gt['trade_pnl']:,.0f}, "
                      f"economic PnL ${gt['economic_pnl']:,.0f} (fees paid ${gt['fees_paid']:,.0f}, maker rebates "
                      f"${gt['maker_rebate']:,.0f})."]
    lines += ["", "## Verdict", ""] + [f"- {v}" for v in r["verdict"]]
    lines += ["", "## Risk controls applied (copy scenarios)", "",
              f"- max position per market: {a['risk']['max_position_pct']:.0%} of equity",
              f"- max daily loss: ${a['risk']['max_daily_loss']:,.0f} (new entries halted for the rest of the UTC day)",
              f"- stop-loss: warning when a position loses > {a['risk']['stop_loss_pct']:.0%} of equity "
              f"(action: {a['risk']['stop_loss_action']})",
              f"- min order: {a['risk']['min_order_shares']} shares / ${a['risk']['min_order_usd']}", "",
              "Files: `performance_report.json`, `backtest_<scenario>_metrics.json|trades.csv.gz|markets.csv|equity.csv`, "
              "`charts/backtest_equity.png`."]
    path.write_text("\n".join(lines), encoding="utf-8")


def print_report(r: dict) -> None:
    bar = "=" * 96
    w = r["window"]
    print(f"\n{bar}\n BACKTEST RESULTS  {w['start_utc']} -> {w['end_utc']}  ({w['fills']:,} fills, {w['markets']:,} markets)\n{bar}")
    print(f" {'scenario':<22}{'equity':>13}{'PnL':>13}{'ret %':>9}{'win %':>8}{'orders':>9}{'fees':>10}{'Sharpe':>9}{'maxDD%':>8}")
    for name, m in r["scenarios"].items():
        sh = m.get("sharpe_hourly_annualized")
        print(f" {name:<22}{m['final_equity']:>13,.2f}{m['total_pnl']:>13,.2f}{m['return_pct']:>9.2f}"
              f"{m.get('win_rate_pct', 0):>8.2f}{m['n_orders']:>9,}{m['fees_paid']:>10,.2f}"
              f"{(sh if sh is not None else float('nan')):>9.2f}{m['max_drawdown_pct']:>8.2f}")
    print(f"{bar}")
    for v in r["verdict"]:
        print(f" * {v}")
    print(f"{bar}\n Saved: reports/performance_report.json, reports/backtest_report.md, reports/charts/backtest_equity.png\n{bar}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--refresh", action="store_true", help="re-download history even if data exists")
    ap.add_argument("--days", type=float, default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.days:
        cfg["backtest"]["days"] = args.days
    if args.refresh or not (Path(cfg["paths"]["data_dir"]) / "trades.csv.gz").exists():
        DataCollector(cfg).run()
    StrategyAnalyzer(cfg).run()
    run_backtest(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
