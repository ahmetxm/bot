"""Live PAPER trading of the strategy replica on the real Polymarket order book (no real orders).

Feeds (all public, millisecond timestamps):
  * Binance spot trades  wss://data-stream.binance.vision  -> fair value (fair_value.LiveFairValue)
  * Polymarket CLOB market websocket (book / price_change / last_trade_price) per market

Paper execution model:
  * Resting BUY quotes go live `latency_seconds` after the decision. They queue behind the size
    already resting at that price (read from the live book). A real taker print at our price first
    consumes the queue ahead of us; a print *through* our price fills us directly. Complementary
    prints (taker BUY of the other outcome at y  ==  hit of our bid at 1-y) count too.
  * Taker orders execute `latency_seconds` later against the then-current book, walking levels up to
    the limit price, paying the Polymarket taker fee rate*p*(1-p) per share.
  * Markets are settled with the official resolution (gamma outcomePrices once closed).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import websocket

from common import TF_SECONDS, load_config, load_json, save_json, setup_logging, utc
from fair_value import LiveFairValue
from market_data import BINANCE_SYMBOL, KLINES_REST
from pair_strategy import Inventory, PairStrategy, StrategyParams, taker_fee_per_share

CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
BINANCE_WS = "wss://data-stream.binance.vision/ws/{stream}"
GAMMA = "https://gamma-api.polymarket.com/markets"
log = logging.getLogger("live_paper")


# --------------------------------------------------------------------------- spot feed
class SpotFeed:
    def __init__(self, assets: list, fv_factory):
        self.fv = {a: fv_factory() for a in assets}
        self.lock = threading.Lock()
        self.last_msg = {a: 0.0 for a in assets}
        self.sess = requests.Session()
        self._stop = False

    def seed(self) -> None:
        now = int(time.time())
        for a, fv in self.fv.items():
            ts, px, cur = [], [], (now - 3700) * 1000
            while cur < now * 1000:
                r = self.sess.get(KLINES_REST, params={"symbol": BINANCE_SYMBOL[a], "interval": "1s",
                                                       "startTime": cur, "limit": 1000}, timeout=20)
                r.raise_for_status()
                rows = r.json()
                if not rows:
                    break
                ts += [int(k[0]) // 1000 for k in rows]; px += [float(k[4]) for k in rows]
                cur = int(rows[-1][0]) + 1000
            dense = np.interp(np.arange(ts[0], ts[-1] + 1), ts, px)
            with self.lock:
                fv.seed(ts[0], dense)
            log.info("spot %s seeded: %d s of history, last %.2f", a, len(dense), px[-1])

    def start(self) -> None:
        for a in self.fv:
            threading.Thread(target=self._run_ws, args=(a,), daemon=True).start()
        threading.Thread(target=self._fallback_poll, daemon=True).start()

    def _run_ws(self, asset: str) -> None:
        stream = f"{BINANCE_SYMBOL[asset].lower()}@aggTrade"

        def on_msg(_ws, msg):
            d = json.loads(msg)
            with self.lock:
                self.fv[asset].update(int(d["T"]) // 1000, float(d["p"]))
                self.last_msg[asset] = time.time()

        while not self._stop:
            ws = websocket.WebSocketApp(BINANCE_WS.format(stream=stream), on_message=on_msg)
            ws.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(2)

    def _fallback_poll(self) -> None:
        while not self._stop:
            for a in self.fv:
                if time.time() - self.last_msg[a] > 3:
                    try:
                        r = self.sess.get("https://data-api.binance.vision/api/v3/ticker/price",
                                          params={"symbol": BINANCE_SYMBOL[a]}, timeout=5).json()
                        with self.lock:
                            self.fv[a].update(int(time.time()), float(r["price"]))
                    except (requests.RequestException, ValueError, KeyError):
                        pass
            time.sleep(1)

    # ---- Chainlink (the resolution source) via Polymarket's public real-time data socket.
    # Binance leads in time; Chainlink defines the level. We track the basis log(CL) - log(Binance)
    # per second and add it to the Binance series, so strike and current level are on Chainlink's scale.
    def start_chainlink(self) -> None:
        self.basis_hist = {a: {} for a in self.fv}     # second -> basis
        self.basis_now = {a: None for a in self.fv}
        self.cl_last = {a: 0.0 for a in self.fv}
        threading.Thread(target=self._run_rtds, daemon=True).start()

    def _run_rtds(self) -> None:
        sym = {f"{a.lower()}/usd": a for a in self.fv}

        def on_open(ws):
            ws.send(json.dumps({"action": "subscribe", "subscriptions": [
                {"topic": "crypto_prices_chainlink", "type": "*", "filters": ""}]}))

        def on_msg(_ws, msg):
            try:
                d = json.loads(msg)
                pl = d.get("payload") or {}
                a = sym.get(pl.get("symbol"))
                if a is None:
                    return
                sec, val = int(pl["timestamp"]) // 1000, float(pl["value"])
            except (ValueError, KeyError, TypeError, AttributeError):
                return
            with self.lock:
                fv = self.fv[a]
                if fv.t0 is None or not (fv.t0 <= sec <= fv.last_t) or val <= 0:
                    return
                b = math.log(val) - fv.logs[sec - fv.t0]
                prev = self.basis_now[a]
                self.basis_now[a] = b if prev is None else 0.8 * prev + 0.2 * b
                self.basis_hist[a][sec] = self.basis_now[a]
                self.cl_last[a] = time.time()
                if len(self.basis_hist[a]) > 8000:
                    for k in sorted(self.basis_hist[a])[:1000]:
                        del self.basis_hist[a][k]

        while not self._stop:
            app = websocket.WebSocketApp("wss://ws-live-data.polymarket.com", on_open=on_open, on_message=on_msg)
            app.run_forever(ping_interval=5, ping_timeout=3)
            time.sleep(2)

    def _shift_fn(self, asset: str):
        hist = getattr(self, "basis_hist", {}).get(asset)
        if not hist or time.time() - self.cl_last.get(asset, 0) > 15:
            return None                    # no fresh Chainlink data -> plain Binance model
        secs = sorted(hist)
        first, now_b = hist[secs[0]], self.basis_now[asset]

        def fn(t0: int, n: int) -> np.ndarray:
            out = np.empty(n)
            last = first
            for k in range(n):        # forward-fill; before the feed started use the first basis seen
                last = hist.get(t0 + k, last)
                out[k] = last
            if secs[-1] - t0 < n - 1:
                out[max(secs[-1] - t0 + 1, 0):] = now_b
            return out
        return fn

    def p_up(self, asset: str, t: int, ws: int, we: int, twap: int) -> Optional[float]:
        with self.lock:
            fv = self.fv[asset]
            if time.time() - self.last_msg[asset] > 10 and fv.last_t < t - 10:
                return None   # stale spot -> no quotes
            return fv.p_up(t, ws, we, twap, self._shift_fn(asset))


# --------------------------------------------------------------------------- market
class PaperMarket:
    def __init__(self, meta: dict, strat: PairStrategy):
        self.meta = meta
        self.strat = strat
        self.inv = Inventory()
        self.books = [{"bids": {}, "asks": {}}, {"bids": {}, "asks": {}}]
        self.quotes: dict = {}         # i -> {"price", "rem", "live_from", "ahead"}
        self.pending_takers: list = []
        self.fair_hist: dict = {}
        self.status = "active"
        self.outcome_up: Optional[float] = None
        self.pnl: Optional[float] = None
        self.ws_app = None
        self.prints = 0
        self.max_cost = 0.0
        # paper taker volume already taken per (outcome, book side, price): a paper fill does not remove
        # the real liquidity, so without this the same resting size could be "bought" again every second
        self.consumed: dict = defaultdict(float)
        self.diag: list = []

    @property
    def ws(self):
        return self.meta["window_start"]

    @property
    def we(self):
        return self.meta["window_end"]

    def best(self, i: int):
        b, a = self.books[i]["bids"], self.books[i]["asks"]
        bb = max((p for p, s in b.items() if s > 0), default=None)
        ba = min((p for p, s in a.items() if s > 0), default=None)
        return bb, ba


class LiveStrategyPaperBot:
    def __init__(self, cfg: dict, params: StrategyParams, tag: str = ""):
        self.cfg = cfg
        self.tag = f"_{tag}" if tag else ""
        self.p = params
        self.bt = cfg["strategy_backtest"]
        self.lat = float(self.bt.get("latency_seconds", 1))
        self.lock = threading.RLock()
        self.sess = requests.Session()
        self.start_balance = float(cfg["paper_trading"]["starting_balance"])
        self.realized = 0.0
        self.daily_realized: dict = defaultdict(float)
        self.markets: dict = {}
        self.fills: list = []
        self.risk = cfg["risk"]
        self.halted_day: Optional[str] = None
        assets = sorted({c.split()[0] for c in params.markets})
        self.spot = SpotFeed(assets, lambda: LiveFairValue(params.vol_halflife_seconds,
                                                           params.vol_multiplier, params.vol_floor))
        self.state_path = Path(cfg["paths"]["data_dir"]) / f"live_paper_state{self.tag}.json"
        self.fills_path = Path(cfg["paths"]["data_dir"]) / f"live_paper_fills{self.tag}.csv"

    # ---- equity / risk
    def equity(self) -> float:
        return self.start_balance + self.realized

    def committed(self) -> float:
        return sum(m.inv.cost_basis for m in self.markets.values() if m.status != "settled")

    # ---- market discovery
    def _fetch_meta(self, slug: str) -> Optional[dict]:
        try:
            res = self.sess.get(GAMMA, params={"slug": slug}, timeout=15).json()
        except (requests.RequestException, ValueError):
            return None
        if not res:
            return None
        m = res[0]
        if not m.get("acceptingOrders"):
            return None
        asset, tf, epoch = slug.split("-")[0].upper(), slug.split("-")[2], int(slug.split("-")[-1])
        fee = m.get("feeSchedule") or {}
        return {"slug": slug, "condition_id": m["conditionId"], "tokens": json.loads(m["clobTokenIds"]),
                "asset": asset, "timeframe": tf, "category": f"{asset} {tf}", "window_start": epoch,
                "window_end": epoch + TF_SECONDS[tf], "fee_rate": float(fee.get("rate", 0) or 0),
                "tick": float(m.get("orderPriceMinTickSize") or 0.01), "min_size": float(m.get("orderMinSize") or 5),
                "twap_lookback": int((m.get("cryptoMarketConfig") or {}).get("twapLookbackSeconds") or 0)}

    def discover(self, now: int, accepting_new: bool) -> None:
        if not accepting_new:
            return
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if self.halted_day == today:
            return
        for cat in self.p.markets:
            asset, tf = cat.split()
            sec = TF_SECONDS[tf]
            start = now - now % sec
            slug = f"{asset.lower()}-updown-{tf}-{start}"
            if slug in self.markets or now > start + sec - self.p.stop_before_end_seconds - 5:
                continue
            budget = min(float(self.risk["max_position_pct"]) * self.equity(), self.p.max_market_usd)
            if self.committed() + budget > self.equity():
                continue
            meta = self._fetch_meta(slug)
            if not meta:
                continue
            m = PaperMarket(meta, PairStrategy(self.p, meta["fee_rate"], meta["tick"], meta["min_size"], budget))
            with self.lock:
                self.markets[slug] = m
            self._start_market_ws(m)
            log.info("tracking %s (budget $%.0f, fee rate %.2f)", slug, budget, meta["fee_rate"])

    def _start_market_ws(self, m: PaperMarket) -> None:
        toks = m.meta["tokens"]

        def on_open(ws):
            ws.send(json.dumps({"assets_ids": toks, "type": "market"}))

        def on_msg(_ws, msg):
            try:
                data = json.loads(msg)
            except ValueError:
                return
            for e in (data if isinstance(data, list) else [data]):
                self._on_event(m, e)

        def runner():
            while m.status == "active":
                app = websocket.WebSocketApp(CLOB_WS, on_open=on_open, on_message=on_msg)
                m.ws_app = app
                app.run_forever(ping_interval=10, ping_timeout=5)
                if m.status == "active":
                    time.sleep(1)

        threading.Thread(target=runner, daemon=True).start()

    # ---- websocket events
    def _on_event(self, m: PaperMarket, e: dict) -> None:
        et = e.get("event_type")
        toks = m.meta["tokens"]
        with self.lock:
            if et == "book" and e.get("asset_id") in toks:
                i = toks.index(e["asset_id"])
                m.books[i]["bids"] = {float(x["price"]): float(x["size"]) for x in e.get("bids", e.get("buys", []))}
                m.books[i]["asks"] = {float(x["price"]): float(x["size"]) for x in e.get("asks", e.get("sells", []))}
            elif et == "price_change":
                for ch in e.get("price_changes", []):
                    if ch.get("asset_id") not in toks:
                        continue
                    i = toks.index(ch["asset_id"])
                    side = "bids" if ch.get("side") == "BUY" else "asks"
                    px, sz = float(ch["price"]), float(ch["size"])
                    if sz <= 0:
                        m.books[i][side].pop(px, None)
                    else:
                        m.books[i][side][px] = sz
                    # (queue ahead of us is only reduced by prints, never by cancellations: conservative,
                    #  because price_change and last_trade_price arrive in no guaranteed order)
            elif et == "last_trade_price" and e.get("asset_id") in toks:
                self._on_print(m, toks.index(e["asset_id"]), e.get("side"), float(e["price"]),
                               float(e["size"]), int(e["timestamp"]) / 1000.0)

    def _on_print(self, m: PaperMarket, oi: int, side: str, px: float, sz: float, ts: float) -> None:
        """A real taker print: does it hit one of our live paper bids?"""
        m.prints += 1
        hit_i, P = (oi, px) if side == "SELL" else (1 - oi, round(1.0 - px, 6))
        q = m.quotes.get(hit_i)
        if not q or q["rem"] <= 1e-9 or ts < q["live_from"]:
            return
        if P < q["price"] - 1e-9:
            f = min(q["rem"], sz)
        elif abs(P - q["price"]) < 1e-9:
            take = sz - q["ahead"]
            q["ahead"] = max(q["ahead"] - sz, 0.0)
            f = min(q["rem"], max(take, 0.0))
        else:
            return
        room = (m.strat.budget - m.inv.cost_basis) / max(q["price"], 0.01)
        f = min(f, max(room, 0.0))
        if f < 0.01:
            return
        reb = float(self.bt.get("maker_rebate_rate", 0.0)) * taker_fee_per_share(q["price"], m.meta["fee_rate"]) * f
        m.inv.apply_buy(hit_i, q["price"], f, 0.0, True, reb)
        q["rem"] -= f
        self._record_fill(m, ts, "BUY", hit_i, q["price"], f, 0.0, "maker")

    def _record_fill(self, m, ts, side, i, price, shares, fee, role):
        row = {"time": utc(ts), "ts": round(ts, 3), "slug": m.meta["slug"], "side": side,
               "outcome": "Up" if i == 0 else "Down", "price": price, "shares": round(shares, 4),
               "fee": round(fee, 5), "role": role}
        self.fills.append(row)
        new = not self.fills_path.exists()
        with open(self.fills_path, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
        log.info("FILL %-5s %s %s %.2f sh @ %.3f fee %.4f (%s) | %s inv Up %.1f Down %.1f cost $%.2f",
                 role, side, row["outcome"], shares, price, fee, m.meta["slug"], m.meta["slug"][:3],
                 m.inv.shares[0], m.inv.shares[1], m.inv.cost_basis)

    # ---- decision loop
    def _step_market(self, m: PaperMarket, now: float) -> None:
        t = int(now)
        if t > m.we - m.strat.p.stop_before_end_seconds or self.halted_day:
            m.quotes.clear(); m.pending_takers.clear()
            return
        fair = self.spot.p_up(m.meta["asset"], t, m.ws, m.we, m.meta["twap_lookback"])
        if fair is None:
            m.quotes.clear()
            return
        m.fair_hist[t] = fair
        bb0, ba0 = m.best(0)
        bb1, ba1 = m.best(1)
        if bb0 is not None and ba0 is not None and ba0 - bb0 <= 0.05 and t % 10 == 0:
            m.diag.append((t, fair, (bb0 + ba0) / 2))     # fair value vs market mid, for the report
        bid, ask = [bb0, bb1], [ba0, ba1]
        # execute taker orders whose latency elapsed, against the current book
        for po in list(m.pending_takers):
            if po["live_from"] > now:
                continue
            m.pending_takers.remove(po)
            self._exec_taker(m, po, now)
        prev = m.fair_hist.get(t - self.p.guard_seconds)
        desired = m.strat.quotes(t, m.ws, m.we, fair, m.inv, bid, ask, prev)
        for i in (0, 1):
            if i not in desired:
                m.quotes.pop(i, None)
                continue
            price, size = desired[i]
            cur = m.quotes.get(i)
            if cur and abs(cur["price"] - price) < self.p.requote_threshold - 1e-9:
                cur["rem"] = max(cur["rem"], size)
                continue
            ahead = m.books[i]["bids"].get(price, 0.0)
            m.quotes[i] = {"price": price, "rem": size, "live_from": now + self.lat, "ahead": ahead}
        busy = {(po["side"], po["i"]) for po in m.pending_takers}
        for side, i, limit, size in m.strat.taker_orders(t, m.ws, m.we, fair, m.inv, bid, ask):
            if (side, i) not in busy:
                m.pending_takers.append({"side": side, "i": i, "limit": limit, "size": size,
                                         "live_from": now + self.lat})
        m.max_cost = max(m.max_cost, m.inv.cost_basis)

    @staticmethod
    def _liq_key(i: int, side: str, px: float) -> tuple:
        """The two outcome books mirror each other (Up ask p == Down bid 1-p), so paper consumption is
        tracked on the Up-equivalent level; otherwise SELL Up and BUY Down could reuse the same size."""
        if i == 0:
            return (side, round(px, 4))
        return ("bids" if side == "asks" else "asks", round(1.0 - px, 4))

    def _exec_taker(self, m: PaperMarket, po: dict, now: float) -> None:
        i, rem = po["i"], po["size"]
        fee_rate = m.meta["fee_rate"]
        if po["side"] == "BUY":
            for px in sorted(p for p, s in m.books[i]["asks"].items() if s > 0):
                if px > po["limit"] + 1e-9 or rem <= 1e-9:
                    break
                room = (m.strat.budget - m.inv.cost_basis) / max(px, 0.01)
                if room < 0.01:
                    break
                avail = m.books[i]["asks"][px] - m.consumed[self._liq_key(i, "asks", px)]
                f = min(rem, avail, room)
                if f < 0.01:
                    continue              # this level was already used up by earlier paper fills
                fee = taker_fee_per_share(px, fee_rate) * f
                m.inv.apply_buy(i, px, f, fee, False)
                m.consumed[self._liq_key(i, "asks", px)] += f
                rem -= f
                self._record_fill(m, now, "BUY", i, px, f, fee, "taker")
        else:
            for px in sorted((p for p, s in m.books[i]["bids"].items() if s > 0), reverse=True):
                if px < po["limit"] - 1e-9 or rem <= 1e-9 or m.inv.shares[i] < 0.01:
                    break
                avail = m.books[i]["bids"][px] - m.consumed[self._liq_key(i, "bids", px)]
                f = min(rem, avail, m.inv.shares[i])
                if f < 0.01:
                    continue
                fee = taker_fee_per_share(px, fee_rate) * f
                m.inv.apply_sell(i, px, f, fee, False)
                m.consumed[self._liq_key(i, "bids", px)] += f
                rem -= f
                self._record_fill(m, now, "SELL", i, px, f, fee, "taker")

    # ---- resolution
    def _check_resolution(self, m: PaperMarket, now: float) -> None:
        if now < m.we + 20 or now - getattr(m, "_last_res_check", 0) < 15:
            return
        m._last_res_check = now
        try:
            res = self.sess.get(GAMMA, params={"slug": m.meta["slug"], "closed": "true"}, timeout=15).json()
        except (requests.RequestException, ValueError):
            return
        if not res:
            return
        prices = [float(x) for x in json.loads(res[0].get("outcomePrices") or "[]")]
        if len(prices) != 2 or max(prices) != 1.0:
            return
        m.pnl = m.inv.settle(prices)
        m.outcome_up = prices[0]
        m.status = "settled"
        if m.ws_app:
            m.ws_app.close()
        day = time.strftime("%Y-%m-%d", time.gmtime(m.we))
        self.realized += m.pnl
        self.daily_realized[day] += m.pnl
        log.info("SETTLED %s -> %s | PnL %+.2f | shares Up %.1f Down %.1f | cost $%.2f | equity $%.2f",
                 m.meta["slug"], "Up" if prices[0] == 1 else "Down", m.pnl, m.inv.shares[0], m.inv.shares[1],
                 m.inv.cost_basis, self.equity())
        if self.daily_realized[day] <= -float(self.risk["max_daily_loss"]):
            self.halted_day = time.strftime("%Y-%m-%d", time.gmtime(now))
            log.warning("DAILY LOSS LIMIT hit (%.2f) - no new quotes today", self.daily_realized[day])

    def _risk_check(self, m: PaperMarket) -> None:
        mids = []
        for i in (0, 1):
            bb, ba = m.best(i)
            mids.append((bb + ba) / 2 if bb is not None and ba is not None else None)
        if None in mids:
            return
        mtm = m.inv.shares[0] * mids[0] + m.inv.shares[1] * mids[1] - m.inv.cost_basis
        if mtm < -float(self.risk["stop_loss_pct"]) * self.equity() and not getattr(m, "_sl_warned", False):
            m._sl_warned = True
            log.warning("STOP-LOSS: %s mark-to-market %.2f < -%.0f%% of equity", m.meta["slug"], mtm,
                        100 * float(self.risk["stop_loss_pct"]))
            if self.risk.get("stop_loss_action") == "close":
                m.strat.budget = m.inv.cost_basis   # no further buys in this market

    # ---- main
    def run(self, minutes: float, settle_wait_minutes: float = 15.0) -> dict:
        self.spot.seed()
        self.spot.start()
        self.spot.start_chainlink()
        time.sleep(3)
        t_end = time.time() + minutes * 60
        last_status = 0.0
        log.info("PAPER strategy bot started: %s | params %s", self.p.markets,
                 {k: v for k, v in self.p.as_dict().items() if k not in ("markets",)})
        while True:
            now = time.time()
            accepting = now < t_end
            self.discover(int(now), accepting)
            with self.lock:
                for m in list(self.markets.values()):
                    if m.status == "active":
                        if now <= m.we:
                            self._step_market(m, now)
                            self._risk_check(m)
                        else:
                            m.quotes.clear()
                            m.status_wait = True
                            self._check_resolution(m, now)
            if now - last_status > 60:
                last_status = now
                self._status(now)
                self.save_state()
            open_m = [m for m in self.markets.values() if m.status != "settled"]
            if not accepting and (not open_m or now > t_end + settle_wait_minutes * 60):
                break
            time.sleep(max(0.05, 1.0 - (time.time() - now)))
        for m in self.markets.values():
            if m.ws_app:
                m.ws_app.close()
        return self.report()

    def _status(self, now):
        act = [m for m in self.markets.values() if m.status == "active"]
        basis = {a: (None if b is None else round(b * 1e4, 2)) for a, b in self.spot.basis_now.items()}
        log.info("STATUS equity $%.2f realized %+.2f | open markets %d | committed $%.2f | fills %d | "
                 "Chainlink-Binance basis (bps) %s", self.equity(), self.realized, len(act), self.committed(),
                 len(self.fills), basis)

    def save_state(self) -> None:
        save_json({"saved_at": utc(time.time()), "equity": self.equity(), "realized": self.realized,
                   "markets": {s: {"status": m.status, "pnl": m.pnl, "inventory": m.inv.to_dict()}
                               for s, m in self.markets.items()}}, self.state_path)

    def report(self) -> dict:
        settled = [m for m in self.markets.values() if m.status == "settled"]
        unsettled = [m for m in self.markets.values() if m.status != "settled"]
        traded = [m for m in settled if m.inv.maker_fills + m.inv.taker_fills > 0]
        buy = sum(m.inv.buy_usdc for m in traded)
        rows = [{"slug": m.meta["slug"], "pnl": m.pnl, "maker_fills": m.inv.maker_fills,
                 "taker_fills": m.inv.taker_fills, "buy_usdc": m.inv.buy_usdc, "fees": m.inv.fees,
                 "shares_up": m.inv.shares[0], "shares_down": m.inv.shares[1], "prints_seen": m.prints}
                for m in settled]
        ll_f = ll_m = 0.0
        n_ll = 0
        for m in settled:
            y = 1.0 if (m.outcome_up or 0) >= 0.5 else 0.0
            for _, f, mid in m.diag:
                f, mid = min(max(f, 1e-3), 1 - 1e-3), min(max(mid, 1e-3), 1 - 1e-3)
                ll_f -= y * math.log(f) + (1 - y) * math.log(1 - f)
                ll_m -= y * math.log(mid) + (1 - y) * math.log(1 - mid)
                n_ll += 1
        out = {"generated_at": utc(time.time()), "params": self.p.as_dict(),
               "logloss_fair_vs_market_mid": ({"fair_value": ll_f / n_ll, "market_mid": ll_m / n_ll,
                                               "samples": n_ll} if n_ll else None),
               "starting_balance": self.start_balance, "final_equity": self.equity(),
               "realized_pnl": self.realized, "markets_settled": len(settled), "markets_traded": len(traded),
               "markets_unsettled": [m.meta["slug"] for m in unsettled],
               "unsettled_cost_basis": sum(m.inv.cost_basis for m in unsettled),
               "win_rate_pct": 100.0 * sum((m.pnl or 0) > 0 for m in traded) / len(traded) if traded else None,
               "buy_usdc": buy, "pnl_per_buy_pct": 100.0 * self.realized / buy if buy else None,
               "fills": len(self.fills), "maker_fills": sum(m.inv.maker_fills for m in settled),
               "taker_fills": sum(m.inv.taker_fills for m in settled),
               "fees": sum(m.inv.fees for m in settled), "markets": rows}
        rep = Path(self.cfg["paths"]["reports_dir"])
        save_json(out, rep / f"live_paper_report{self.tag}.json")
        L = ["# Live paper trading - strategy replica", "",
             f"Generated {out['generated_at']}. No real orders were sent; fills are simulated against the live "
             "Polymarket order book and live trade prints (see live_paper.py docstring).", "",
             f"- Starting balance: ${self.start_balance:,.2f} -> final equity ${out['final_equity']:,.2f}",
             f"- Realized PnL: ${self.realized:+,.2f} over {len(settled)} settled markets ({len(traded)} with fills)",
             f"- Win rate (traded markets): {out['win_rate_pct'] if out['win_rate_pct'] is None else round(out['win_rate_pct'], 1)}%",
             f"- Bought ${buy:,.2f}; PnL / buys: {out['pnl_per_buy_pct'] if out['pnl_per_buy_pct'] is None else round(out['pnl_per_buy_pct'], 2)}%",
             f"- Fills: {out['maker_fills']} maker / {out['taker_fills']} taker, fees ${out['fees']:.2f}",
             f"- Unsettled at report time: {len(unsettled)} (cost basis ${out['unsettled_cost_basis']:.2f})",
             f"- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): "
             f"{out['logloss_fair_vs_market_mid']}", "",
             "| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
        L += [f"| {r['slug']} | ${(r['pnl'] or 0):+.2f} | {r['maker_fills']} | {r['taker_fills']} | ${r['buy_usdc']:.2f} | "
              f"{r['shares_up']:.1f} | {r['shares_down']:.1f} | {r['prints_seen']} |" for r in rows]
        (rep / f"live_paper_report{self.tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        log.info("REPORT: realized %+.2f over %d markets (%d traded), fills %d", self.realized, len(settled),
                 len(traded), len(self.fills))
        return out


def load_params(cfg: dict, use_calibrated: bool = True) -> StrategyParams:
    cal = load_json(Path(cfg["paths"]["data_dir"]) / "calibrated_params.json") if use_calibrated else None
    if cal and cal.get("params"):
        return StrategyParams(**cal["params"])
    return StrategyParams.from_cfg(cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Live PAPER trading of the strategy replica")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--config-params", action="store_true", help="ignore data/calibrated_params.json")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a strategy parameter, e.g. --set take_enabled=false")
    ap.add_argument("--tag", default="", help="suffix for state/fills/report files (parallel runs)")
    args = ap.parse_args(argv)
    cfg = load_config()
    global log
    log = setup_logging(cfg, "live_paper" + (f"_{args.tag}" if args.tag else ""))
    params = load_params(cfg, not args.config_params)
    if args.set:
        d = params.as_dict()
        for kv in args.set:
            k, v = kv.split("=", 1)
            d[k] = json.loads(v) if v not in ("true", "false") else v == "true"
        params = StrategyParams(**d)
    bot = LiveStrategyPaperBot(cfg, params, args.tag)
    out = bot.run(args.minutes)
    print(json.dumps({k: v for k, v in out.items() if k not in ("markets", "params")}, indent=1, default=str))


if __name__ == "__main__":
    main()
