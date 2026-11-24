"""Live PAPER trading of the strategy replica on the real Polymarket order book (no real orders).

Feeds (all public, millisecond timestamps):
  * Binance spot trades  wss://data-stream.binance.vision  -> fair value (fair_value.LiveFairValue)
    (fallback: Coinbase ticker websocket, e.g. on hosts where Binance is geo-blocked)
  * Chainlink BTC/ETH prices (the resolution source) via Polymarket's real-time data socket
  * Polymarket CLOB market websocket (book / price_change / last_trade_price) per market

Several strategy VARIANTS can run side by side on the same live feed (--variants file.json); each has its own
paper account, inventory, quotes and risk limits, so their results are directly comparable.

Paper execution model:
  * Resting BUY quotes go live `latency` seconds after the decision. They queue behind the size
    already resting at that price (read from the live book). A real taker print at our price first
    consumes the queue ahead of us; a print *through* our price fills us directly. Complementary
    prints (taker BUY of the other outcome at y  ==  hit of our bid at 1-y) count too.
  * Taker orders execute `latency` seconds later against the then-current book, walking levels up to
    the limit price, paying the Polymarket taker fee rate*p*(1-p) per share.
  * Markets are settled with the official resolution (gamma outcomePrices once closed).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import math
import signal
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
BINANCE_TICKER = "https://data-api.binance.vision/api/v3/ticker/price"
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{pid}/candles"
COINBASE_PID = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD"}
GAMMA = "https://gamma-api.polymarket.com/markets"
VOL_KEYS = ("vol_halflife_seconds", "vol_multiplier", "vol_floor_bps_per_sqrt_s")
log = logging.getLogger("live_paper")


# --------------------------------------------------------------------------- raw feed recording
class Recorder:
    """Optional gzip JSON-lines recording of the raw feeds ([local_ts, kind, ...]) for offline research."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.fh = gzip.open(path, "at", encoding="utf-8") if path else None
        self.lock = threading.Lock()
        self.n = 0

    def write(self, *rec) -> None:
        if self.fh is None:
            return
        line = json.dumps([round(time.time(), 3), *rec], separators=(",", ":"))
        with self.lock:
            if self.fh is None:
                return
            self.fh.write(line + "\n")
            self.n += 1
            if self.n % 5000 == 0:
                self.fh.flush()

    def close(self) -> None:
        with self.lock:
            if self.fh is not None:
                self.fh.close()
                self.fh = None


# --------------------------------------------------------------------------- spot feed
class SpotFeed:
    def __init__(self, assets: list, fv_factory, rec: Optional[Recorder] = None):
        self.fv = {a: fv_factory() for a in assets}
        self.lock = threading.Lock()
        self.last_msg = {a: 0.0 for a in assets}
        self.source = {a: "binance" for a in assets}
        self.sess = requests.Session()
        self.rec = rec or Recorder(None)
        self._pend: dict = {}
        self._stop = False
        self.basis_hist = {a: {} for a in assets}     # second -> Chainlink-Binance log basis
        self.basis_now = {a: None for a in assets}
        self.cl_last = {a: 0.0 for a in assets}

    # ---- history seed (1 h of 1 s closes for the volatility estimate and the window-start strike)
    def _seed_binance(self, a: str):
        now = int(time.time())
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
        return ts[0], np.interp(np.arange(ts[0], ts[-1] + 1), ts, px)

    def _seed_coinbase(self, a: str):
        now = int(time.time())
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
        r = self.sess.get(COINBASE_CANDLES.format(pid=COINBASE_PID[a]),
                          params={"granularity": 60, "start": iso(now - 3700), "end": iso(now)}, timeout=20)
        r.raise_for_status()
        rows = sorted(r.json())                       # [time, low, high, open, close, volume]
        ts = np.array([int(x[0]) for x in rows]); px = np.array([float(x[4]) for x in rows])
        secs = np.arange(ts[0], now + 1)
        # step (forward-fill), not linear interpolation: keeps the per-second variance estimate unbiased
        return int(ts[0]), px[np.searchsorted(ts, secs, side="right") - 1]

    def seed(self) -> None:
        for a, fv in self.fv.items():
            try:
                t0, dense = self._seed_binance(a)
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                log.warning("Binance history unavailable for %s (%s) -> Coinbase 1-min candles + Coinbase feed", a, e)
                self.source[a] = "coinbase"
                t0, dense = self._seed_coinbase(a)
            with self.lock:
                fv.seed(t0, dense)
            self.rec.write("seed", a, int(t0), [round(float(x), 3) for x in dense])
            log.info("spot %s seeded from %s: %d s of history, last %.2f", a, self.source[a], len(dense), dense[-1])

    def start(self) -> None:
        for a in self.fv:
            target = self._run_binance if self.source[a] == "binance" else self._run_coinbase
            threading.Thread(target=target, args=(a,), daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _update(self, asset: str, sec: int, px: float) -> None:
        with self.lock:
            self.fv[asset].update(sec, px)
            self.last_msg[asset] = time.time()
        prev = self._pend.get(asset)
        if prev and prev[0] != sec:
            self.rec.write("spot", asset, prev[0], prev[1])   # last price of each second
        self._pend[asset] = (sec, px)

    def _run_binance(self, asset: str) -> None:
        stream = f"{BINANCE_SYMBOL[asset].lower()}@aggTrade"

        def on_msg(_ws, msg):
            try:
                d = json.loads(msg)
                self._update(asset, int(d["T"]) // 1000, float(d["p"]))
            except (ValueError, KeyError, TypeError):
                pass

        while not self._stop and self.source[asset] == "binance":
            ws = websocket.WebSocketApp(BINANCE_WS.format(stream=stream), on_message=on_msg)
            ws.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(2)

    def _run_coinbase(self, asset: str) -> None:
        pid = COINBASE_PID[asset]

        def on_open(ws):
            ws.send(json.dumps({"type": "subscribe", "product_ids": [pid], "channels": ["ticker"]}))

        def on_msg(_ws, msg):
            try:
                d = json.loads(msg)
                if d.get("type") == "ticker":
                    self._update(asset, int(time.time()), float(d["price"]))
            except (ValueError, KeyError, TypeError):
                pass

        while not self._stop:
            app = websocket.WebSocketApp(COINBASE_WS, on_open=on_open, on_message=on_msg)
            app.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(2)

    def _watchdog(self) -> None:
        """Binance websocket silent -> poll Binance REST; Binance unreachable for 20 s -> switch to Coinbase."""
        fails: dict = defaultdict(int)
        while not self._stop:
            for a in self.fv:
                if self.source[a] != "binance" or time.time() - self.last_msg[a] <= 3:
                    continue
                try:
                    r = self.sess.get(BINANCE_TICKER, params={"symbol": BINANCE_SYMBOL[a]}, timeout=5)
                    r.raise_for_status()
                    self._update(a, int(time.time()), float(r.json()["price"]))
                    fails[a] = 0
                except (requests.RequestException, ValueError, KeyError):
                    fails[a] += 1
                    if fails[a] >= 20:
                        log.warning("Binance unreachable for %s -> switching the spot feed to Coinbase", a)
                        self.source[a] = "coinbase"
                        threading.Thread(target=self._run_coinbase, args=(a,), daemon=True).start()
            time.sleep(1)

    # ---- Chainlink (the resolution source) via Polymarket's public real-time data socket.
    # Binance leads in time; Chainlink defines the level. We track the basis log(CL) - log(spot feed)
    # per second and add it to the spot series, so strike and current level are on Chainlink's scale.
    def start_chainlink(self) -> None:
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
            self.rec.write("cl", a, sec, val)
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
        hist = self.basis_hist.get(asset)
        if not hist or time.time() - self.cl_last.get(asset, 0) > 15:
            return None                    # no fresh Chainlink data -> plain spot model
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


# --------------------------------------------------------------------------- accounts / markets
class Variant:
    """One strategy configuration with its own paper account."""

    def __init__(self, name: str, params: StrategyParams, start_balance: float, data_dir: Path, tag: str,
                 latency: float, interval: float):
        self.name = name
        self.p = params
        self.start_balance = start_balance
        self.latency = latency            # decision -> order live (seconds)
        self.interval = interval          # seconds between decisions
        self.realized = 0.0
        self.daily_realized: dict = defaultdict(float)
        self.halted_day: Optional[str] = None
        self.n_fills = 0
        self.suffix = tag + (f"_{name}" if name else "")
        self.fills_path = data_dir / f"live_paper_fills{self.suffix}.csv"

    def equity(self) -> float:
        return self.start_balance + self.realized


class VariantMarket:
    """A variant's state in one market."""

    def __init__(self, strat: PairStrategy):
        self.strat = strat
        self.inv = Inventory()
        self.quotes: dict = {}         # i -> {"price", "rem", "live_from", "ahead"}
        self.pending_takers: list = []
        # paper taker volume already taken per (book side, Up-equivalent price): a paper fill does not remove
        # the real liquidity, so without this the same resting size could be "bought" again every second
        self.consumed: dict = defaultdict(float)
        self.pnl: Optional[float] = None
        self.max_cost = 0.0
        self.last_decision = 0.0
        self.sl_warned = False


class PaperMarket:
    """Shared live state of one market (books, prints, fair value) + per-variant state."""

    def __init__(self, meta: dict):
        self.meta = meta
        self.books = [{"bids": {}, "asks": {}}, {"bids": {}, "asks": {}}]
        self.fair_hist: dict = {}
        self.status = "active"
        self.outcome_up: Optional[float] = None
        self.ws_app = None
        self.prints = 0
        self.diag: list = []
        self.vm: dict = {}             # variant name -> VariantMarket
        self.rec_book_ts = 0.0         # last recorded book snapshot (Recorder throttle)

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
    def __init__(self, cfg: dict, variants, tag: str = "", record: bool = False, tick_seconds: float = 1.0,
                 interim_report_seconds: float = 0.0):
        """variants: StrategyParams (single, unnamed variant) or a list of dicts
        {"name", "params": StrategyParams, "latency": s (optional), "interval": s (optional)}."""
        self.cfg = cfg
        self.tag = f"_{tag}" if tag else ""
        self.bt = cfg["strategy_backtest"]
        self.lat = float(self.bt.get("latency_seconds", 1))
        self.tick = float(tick_seconds)
        self.interim_report_seconds = float(interim_report_seconds)
        self.lock = threading.RLock()
        self.sess = requests.Session()
        self.start_balance = float(cfg["paper_trading"]["starting_balance"])
        self.risk = cfg["risk"]
        data_dir = Path(cfg["paths"]["data_dir"])
        if isinstance(variants, StrategyParams):
            variants = [{"name": "", "params": variants}]
        self.variants = [Variant(v["name"], v["params"], self.start_balance, data_dir, self.tag,
                                 float(v.get("latency", self.lat)), float(v.get("interval", 1.0)))
                         for v in variants]
        names = [v.name for v in self.variants]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate variant names: {names}")
        self.vmap = {v.name: v for v in self.variants}
        p0 = self.variants[0].p
        for v in self.variants[1:]:                  # the fair value is shared -> same volatility model
            if any(getattr(v.p, k) != getattr(p0, k) for k in VOL_KEYS):
                log.warning("variant %s: volatility parameters replaced by %s's (shared fair value)",
                            v.name, self.variants[0].name)
                v.p = StrategyParams(**{**v.p.as_dict(), **{k: getattr(p0, k) for k in VOL_KEYS}})
        self.p = p0
        self.categories = sorted({c for v in self.variants for c in v.p.markets})
        self.markets: dict = {}
        rec_path = None
        if record:
            (data_dir / "recordings").mkdir(parents=True, exist_ok=True)
            rec_path = data_dir / "recordings" / f"feed{self.tag}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}.jsonl.gz"
        self.rec = Recorder(rec_path)
        assets = sorted({c.split()[0] for c in self.categories})
        self.spot = SpotFeed(assets, lambda: LiveFairValue(p0.vol_halflife_seconds, p0.vol_multiplier,
                                                           p0.vol_floor), self.rec)
        self.state_path = data_dir / f"live_paper_state{self.tag}.json"

    # ---- equity / risk
    def committed(self, v: Variant) -> float:
        return sum(m.vm[v.name].inv.cost_basis for m in self.markets.values()
                   if m.status != "settled" and v.name in m.vm)

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
        for cat in self.categories:
            asset, tf = cat.split()
            sec = TF_SECONDS[tf]
            start = now - now % sec
            slug = f"{asset.lower()}-updown-{tf}-{start}"
            if slug in self.markets:
                continue
            members = [v for v in self.variants if cat in v.p.markets and v.halted_day != today]
            if not members or now > start + sec - min(v.p.stop_before_end_seconds for v in members) - 5:
                continue
            wanted = []
            for v in members:
                budget = min(float(self.risk["max_position_pct"]) * v.equity(), v.p.max_market_usd)
                if self.committed(v) + budget <= v.equity():
                    wanted.append((v, budget))
            if not wanted:
                continue
            meta = self._fetch_meta(slug)
            if not meta:
                continue
            m = PaperMarket(meta)
            for v, budget in wanted:
                m.vm[v.name] = VariantMarket(PairStrategy(v.p, meta["fee_rate"], meta["tick"], meta["min_size"], budget))
            with self.lock:
                self.markets[slug] = m
            self.rec.write("meta", meta)
            self._start_market_ws(m)
            log.info("tracking %s (%d variant(s), fee rate %.2f)", slug, len(wanted), meta["fee_rate"])

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
            if self.rec.fh is not None:
                self._record_clob(m, data)

        def runner():
            while m.status == "active":
                app = websocket.WebSocketApp(CLOB_WS, on_open=on_open, on_message=on_msg)
                m.ws_app = app
                app.run_forever(ping_interval=10, ping_timeout=5)
                if m.status == "active":
                    time.sleep(1)

        threading.Thread(target=runner, daemon=True).start()

    def _record_clob(self, m: PaperMarket, data) -> None:
        """Compact recording (the raw feed is ~100 MB/min): every trade print, plus the top 5 book levels of
        both outcomes at most every 0.25 s when the book changed."""
        toks, slug, changed = m.meta["tokens"], m.meta["slug"], False
        for e in (data if isinstance(data, list) else [data]):
            if not isinstance(e, dict):
                continue
            if e.get("event_type") == "last_trade_price" and e.get("asset_id") in toks:
                self.rec.write("trade", slug, toks.index(e["asset_id"]), e.get("side"), float(e["price"]),
                               float(e["size"]), int(e["timestamp"]) / 1000.0)
            elif e.get("event_type") in ("book", "price_change"):
                changed = True
        now = time.time()
        if changed and now - m.rec_book_ts >= 0.25:
            m.rec_book_ts = now
            with self.lock:
                top = [[sorted(b["bids"].items(), reverse=True)[:5], sorted(b["asks"].items())[:5]] for b in m.books]
            self.rec.write("book", slug, top)

    # ---- websocket events
    def _on_event(self, m: PaperMarket, e: dict) -> None:
        if not isinstance(e, dict):
            return
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
        """A real taker print: does it hit one of our live paper bids (in any variant)?"""
        m.prints += 1
        hit_i, P = (oi, px) if side == "SELL" else (1 - oi, round(1.0 - px, 6))
        for name, vm in m.vm.items():
            q = vm.quotes.get(hit_i)
            if not q or q["rem"] <= 1e-9 or ts < q["live_from"]:
                continue
            if P < q["price"] - 1e-9:
                f = min(q["rem"], sz)
            elif abs(P - q["price"]) < 1e-9:
                take = sz - q["ahead"]
                q["ahead"] = max(q["ahead"] - sz, 0.0)
                f = min(q["rem"], max(take, 0.0))
            else:
                continue
            room = (vm.strat.budget - vm.inv.cost_basis) / max(q["price"], 0.01)
            f = min(f, max(room, 0.0))
            if f < 0.01:
                continue
            reb = float(self.bt.get("maker_rebate_rate", 0.0)) * taker_fee_per_share(q["price"], m.meta["fee_rate"]) * f
            vm.inv.apply_buy(hit_i, q["price"], f, 0.0, True, reb)
            q["rem"] -= f
            self._record_fill(m, self.vmap[name], ts, "BUY", hit_i, q["price"], f, 0.0, "maker")

    def _record_fill(self, m, v: Variant, ts, side, i, price, shares, fee, role):
        vm = m.vm[v.name]
        v.n_fills += 1
        row = {"time": utc(ts), "ts": round(ts, 3), "variant": v.name, "slug": m.meta["slug"], "side": side,
               "outcome": "Up" if i == 0 else "Down", "price": price, "shares": round(shares, 4),
               "fee": round(fee, 5), "role": role}
        new = not v.fills_path.exists()
        with open(v.fills_path, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
        log.info("FILL %s%-5s %s %s %.2f sh @ %.3f fee %.4f | %s inv Up %.1f Down %.1f cost $%.2f",
                 f"[{v.name}] " if v.name else "", role, side, row["outcome"], shares, price, fee,
                 m.meta["slug"], vm.inv.shares[0], vm.inv.shares[1], vm.inv.cost_basis)

    # ---- decision loop
    def _step_market(self, m: PaperMarket, now: float) -> None:
        t = int(now)
        fair = self.spot.p_up(m.meta["asset"], t, m.ws, m.we, m.meta["twap_lookback"])
        if fair is None:
            for vm in m.vm.values():
                vm.quotes.clear()
            return
        m.fair_hist[t] = fair
        bb0, ba0 = m.best(0)
        bb1, ba1 = m.best(1)
        if bb0 is not None and ba0 is not None and ba0 - bb0 <= 0.05 and t % 10 == 0 and \
                (not m.diag or m.diag[-1][0] != t):
            m.diag.append((t, fair, (bb0 + ba0) / 2))     # fair value vs market mid, for the report
        bid, ask = [bb0, bb1], [ba0, ba1]
        for name, vm in m.vm.items():
            v = self.vmap[name]
            # execute taker orders whose latency elapsed, against the current book
            for po in list(vm.pending_takers):
                if po["live_from"] <= now:
                    vm.pending_takers.remove(po)
                    self._exec_taker(m, v, po, now)
            if t > m.we - vm.strat.p.stop_before_end_seconds or v.halted_day:
                vm.quotes.clear(); vm.pending_takers.clear()
                continue
            if now - vm.last_decision < v.interval - 1e-6:
                continue
            vm.last_decision = now
            prev = m.fair_hist.get(t - vm.strat.p.guard_seconds)
            desired = vm.strat.quotes(t, m.ws, m.we, fair, vm.inv, bid, ask, prev)
            for i in (0, 1):
                if i not in desired:
                    vm.quotes.pop(i, None)
                    continue
                price, size = desired[i]
                cur = vm.quotes.get(i)
                if cur and abs(cur["price"] - price) < vm.strat.p.requote_threshold - 1e-9:
                    cur["rem"] = max(cur["rem"], size)
                    continue
                ahead = m.books[i]["bids"].get(price, 0.0)
                vm.quotes[i] = {"price": price, "rem": size, "live_from": now + v.latency, "ahead": ahead}
            busy = {(po["side"], po["i"]) for po in vm.pending_takers}
            for side, i, limit, size in vm.strat.taker_orders(t, m.ws, m.we, fair, vm.inv, bid, ask):
                if (side, i) not in busy:
                    vm.pending_takers.append({"side": side, "i": i, "limit": limit, "size": size,
                                              "live_from": now + v.latency})
            vm.max_cost = max(vm.max_cost, vm.inv.cost_basis)

    @staticmethod
    def _liq_key(i: int, side: str, px: float) -> tuple:
        """The two outcome books mirror each other (Up ask p == Down bid 1-p), so paper consumption is
        tracked on the Up-equivalent level; otherwise SELL Up and BUY Down could reuse the same size."""
        if i == 0:
            return (side, round(px, 4))
        return ("bids" if side == "asks" else "asks", round(1.0 - px, 4))

    def _exec_taker(self, m: PaperMarket, v: Variant, po: dict, now: float) -> None:
        vm = m.vm[v.name]
        i, rem = po["i"], po["size"]
        fee_rate = m.meta["fee_rate"]
        if po["side"] == "BUY":
            for px in sorted(p for p, s in m.books[i]["asks"].items() if s > 0):
                if px > po["limit"] + 1e-9 or rem <= 1e-9:
                    break
                room = (vm.strat.budget - vm.inv.cost_basis) / max(px, 0.01)
                if room < 0.01:
                    break
                avail = m.books[i]["asks"][px] - vm.consumed[self._liq_key(i, "asks", px)]
                f = min(rem, avail, room)
                if f < 0.01:
                    continue              # this level was already used up by earlier paper fills
                fee = taker_fee_per_share(px, fee_rate) * f
                vm.inv.apply_buy(i, px, f, fee, False)
                vm.consumed[self._liq_key(i, "asks", px)] += f
                rem -= f
                self._record_fill(m, v, now, "BUY", i, px, f, fee, "taker")
        else:
            for px in sorted((p for p, s in m.books[i]["bids"].items() if s > 0), reverse=True):
                if px < po["limit"] - 1e-9 or rem <= 1e-9 or vm.inv.shares[i] < 0.01:
                    break
                avail = m.books[i]["bids"][px] - vm.consumed[self._liq_key(i, "bids", px)]
                f = min(rem, avail, vm.inv.shares[i])
                if f < 0.01:
                    continue
                fee = taker_fee_per_share(px, fee_rate) * f
                vm.inv.apply_sell(i, px, f, fee, False)
                vm.consumed[self._liq_key(i, "bids", px)] += f
                rem -= f
                self._record_fill(m, v, now, "SELL", i, px, f, fee, "taker")

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
        m.outcome_up = prices[0]
        m.status = "settled"
        if m.ws_app:
            m.ws_app.close()
        self.rec.write("res", m.meta["slug"], prices)
        day = time.strftime("%Y-%m-%d", time.gmtime(m.we))
        parts = []
        for name, vm in m.vm.items():
            v = self.vmap[name]
            vm.pnl = vm.inv.settle(prices)
            v.realized += vm.pnl
            v.daily_realized[day] += vm.pnl
            parts.append(f"{name or 'pnl'} {vm.pnl:+.2f} (cost ${vm.inv.cost_basis:.0f}, eq ${v.equity():,.0f})")
            if v.daily_realized[day] <= -float(self.risk["max_daily_loss"]) and not v.halted_day:
                v.halted_day = time.strftime("%Y-%m-%d", time.gmtime(now))
                log.warning("DAILY LOSS LIMIT hit for %s (%.2f) - no new quotes today", name or "bot",
                            v.daily_realized[day])
        log.info("SETTLED %s -> %s | %s", m.meta["slug"], "Up" if prices[0] == 1 else "Down", " | ".join(parts))

    def _risk_check(self, m: PaperMarket) -> None:
        mids = []
        for i in (0, 1):
            bb, ba = m.best(i)
            mids.append((bb + ba) / 2 if bb is not None and ba is not None else None)
        if None in mids:
            return
        for name, vm in m.vm.items():
            v = self.vmap[name]
            mtm = vm.inv.shares[0] * mids[0] + vm.inv.shares[1] * mids[1] - vm.inv.cost_basis
            if mtm < -float(self.risk["stop_loss_pct"]) * v.equity() and not vm.sl_warned:
                vm.sl_warned = True
                log.warning("STOP-LOSS [%s]: %s mark-to-market %.2f < -%.0f%% of equity", name, m.meta["slug"], mtm,
                            100 * float(self.risk["stop_loss_pct"]))
                if self.risk.get("stop_loss_action") == "close":
                    vm.strat.budget = vm.inv.cost_basis   # no further buys in this market

    # ---- main
    def run(self, minutes: float, settle_wait_minutes: float = 15.0) -> list:
        self.spot.seed()
        self.spot.start()
        self.spot.start_chainlink()
        time.sleep(3)
        t_end = time.time() + minutes * 60
        last_status = last_report = time.time()
        for v in self.variants:
            log.info("PAPER variant %s started: %s | latency %.2fs interval %.2fs | params %s", v.name or "-",
                     v.p.markets, v.latency, v.interval,
                     {k: val for k, val in v.p.as_dict().items() if k != "markets"})
        try:
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
                                for vm in m.vm.values():
                                    vm.quotes.clear()
                                self._check_resolution(m, now)
                if now - last_status > 60:
                    last_status = now
                    self._status()
                    self.save_state()
                if self.interim_report_seconds and now - last_report > self.interim_report_seconds:
                    last_report = now
                    with self.lock:
                        self.report()  # interim snapshot, so a killed run still leaves results behind
                open_m = [m for m in self.markets.values() if m.status != "settled"]
                if not accepting and (not open_m or now > t_end + settle_wait_minutes * 60):
                    break
                time.sleep(max(0.02, self.tick - (time.time() - now)))
        except KeyboardInterrupt:
            log.warning("interrupted - writing the report for the markets settled so far")
        finally:
            for m in self.markets.values():
                if m.ws_app:
                    m.ws_app.close()
            self.rec.close()
        return self.report()

    def _status(self):
        act = sum(m.status == "active" for m in self.markets.values())
        basis = {a: (None if b is None else round(b * 1e4, 2)) for a, b in self.spot.basis_now.items()}
        eq = " | ".join(f"{v.name or 'equity'} ${v.equity():,.2f} ({v.realized:+.2f}, {v.n_fills} fills)"
                        for v in self.variants)
        log.info("STATUS %s | open markets %d | spot %s | Chainlink basis (bps) %s", eq, act, self.spot.source, basis)

    def save_state(self) -> None:
        save_json({"saved_at": utc(time.time()),
                   "variants": {v.name: {"equity": v.equity(), "realized": v.realized, "fills": v.n_fills,
                                         "halted_day": v.halted_day} for v in self.variants},
                   "markets": {s: {"status": m.status, "outcome_up": m.outcome_up,
                                   "variants": {n: {"pnl": vm.pnl, "inventory": vm.inv.to_dict()}
                                                for n, vm in m.vm.items()}}
                               for s, m in self.markets.items()}}, self.state_path)

    # ---- reporting
    def _logloss(self) -> Optional[dict]:
        ll_f = ll_m = 0.0
        n = 0
        for m in self.markets.values():
            if m.status != "settled":
                continue
            y = 1.0 if (m.outcome_up or 0) >= 0.5 else 0.0
            for _, f, mid in m.diag:
                f, mid = min(max(f, 1e-3), 1 - 1e-3), min(max(mid, 1e-3), 1 - 1e-3)
                ll_f -= y * math.log(f) + (1 - y) * math.log(1 - f)
                ll_m -= y * math.log(mid) + (1 - y) * math.log(1 - mid)
                n += 1
        return {"fair_value": ll_f / n, "market_mid": ll_m / n, "samples": n} if n else None

    def _variant_report(self, v: Variant, logloss: Optional[dict]) -> dict:
        mine = [m for m in self.markets.values() if v.name in m.vm]
        settled = [m for m in mine if m.status == "settled"]
        unsettled = [m for m in mine if m.status != "settled"]
        traded = [m for m in settled if m.vm[v.name].inv.maker_fills + m.vm[v.name].inv.taker_fills > 0]
        buy = sum(m.vm[v.name].inv.buy_usdc for m in traded)
        rows = []
        for m in settled:
            vm = m.vm[v.name]
            rows.append({"slug": m.meta["slug"], "category": m.meta["category"], "outcome_up": m.outcome_up,
                         "pnl": vm.pnl, "maker_fills": vm.inv.maker_fills, "taker_fills": vm.inv.taker_fills,
                         "buy_usdc": vm.inv.buy_usdc, "fees": vm.inv.fees, "shares_up": vm.inv.shares[0],
                         "shares_down": vm.inv.shares[1], "prints_seen": m.prints})
        by_cat: dict = defaultdict(lambda: {"markets": 0, "pnl": 0.0, "buy_usdc": 0.0, "wins": 0})
        for r in rows:
            if r["maker_fills"] + r["taker_fills"] == 0:
                continue
            c = by_cat[r["category"]]
            c["markets"] += 1; c["pnl"] += r["pnl"] or 0.0; c["buy_usdc"] += r["buy_usdc"]; c["wins"] += (r["pnl"] or 0) > 0
        out = {"generated_at": utc(time.time()), "variant": v.name, "params": v.p.as_dict(),
               "latency_seconds": v.latency, "decision_interval_seconds": v.interval,
               "logloss_fair_vs_market_mid": logloss,
               "starting_balance": self.start_balance, "final_equity": v.equity(),
               "realized_pnl": v.realized, "markets_settled": len(settled), "markets_traded": len(traded),
               "markets_unsettled": [m.meta["slug"] for m in unsettled],
               "unsettled_cost_basis": sum(m.vm[v.name].inv.cost_basis for m in unsettled),
               "win_rate_pct": 100.0 * sum((m.vm[v.name].pnl or 0) > 0 for m in traded) / len(traded) if traded else None,
               "buy_usdc": buy, "pnl_per_buy_pct": 100.0 * v.realized / buy if buy else None,
               "fills": v.n_fills, "maker_fills": sum(m.vm[v.name].inv.maker_fills for m in settled),
               "taker_fills": sum(m.vm[v.name].inv.taker_fills for m in settled),
               "fees": sum(m.vm[v.name].inv.fees for m in settled), "by_category": dict(by_cat),
               "halted_day": v.halted_day, "markets": rows}
        rep = Path(self.cfg["paths"]["reports_dir"])
        save_json(out, rep / f"live_paper_report{v.suffix}.json")
        fmt = lambda x, d=1: "n/a" if x is None else f"{x:.{d}f}%"  # noqa: E731
        L = [f"# Live paper trading - strategy replica{(' - variant ' + v.name) if v.name else ''}", "",
             f"Generated {out['generated_at']}. No real orders were sent; fills are simulated against the live "
             "Polymarket order book and live trade prints (see live_paper.py docstring).", "",
             f"- Latency {v.latency:.2f} s, decision every {v.interval:.2f} s, markets {v.p.markets}",
             f"- Starting balance: ${self.start_balance:,.2f} -> final equity ${out['final_equity']:,.2f}",
             f"- Realized PnL: ${v.realized:+,.2f} over {len(settled)} settled markets ({len(traded)} with fills)",
             f"- Win rate (traded markets): {fmt(out['win_rate_pct'])}",
             f"- Bought ${buy:,.2f}; PnL / buys: {fmt(out['pnl_per_buy_pct'], 2)}",
             f"- Fills: {out['maker_fills']} maker / {out['taker_fills']} taker, fees ${out['fees']:.2f}",
             f"- Unsettled at report time: {len(unsettled)} (cost basis ${out['unsettled_cost_basis']:.2f})",
             f"- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {logloss}", "",
             "| category | markets | PnL | win rate | PnL / buys |", "|---|---:|---:|---:|---:|"]
        L += [f"| {c} | {d['markets']} | ${d['pnl']:+.2f} | {100.0 * d['wins'] / d['markets']:.1f}% | "
              f"{(100.0 * d['pnl'] / d['buy_usdc']) if d['buy_usdc'] else 0:.2f}% |" for c, d in sorted(by_cat.items())]
        L += ["", "| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        L += [f"| {r['slug']} | ${(r['pnl'] or 0):+.2f} | {r['maker_fills']} | {r['taker_fills']} | ${r['buy_usdc']:.2f} | "
              f"{r['shares_up']:.1f} | {r['shares_down']:.1f} | {r['prints_seen']} |" for r in rows]
        (rep / f"live_paper_report{v.suffix}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        log.info("REPORT %s: realized %+.2f over %d markets (%d traded), fills %d", v.name or "-", v.realized,
                 len(settled), len(traded), v.n_fills)
        return out

    def report(self) -> list:
        ll = self._logloss()
        outs = [self._variant_report(v, ll) for v in self.variants]
        if len(outs) > 1:
            rep = Path(self.cfg["paths"]["reports_dir"])
            fmt = lambda x, d=2: "n/a" if x is None else f"{x:.{d}f}%"  # noqa: E731
            L = ["# Live paper trading - variant comparison (same live feed)", "",
                 f"Generated {utc(time.time())}. No real orders were sent.", "",
                 "| variant | markets | latency | PnL | PnL / buys | win rate | bought | maker / taker | fees |",
                 "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
            L += [f"| {o['variant']} | {', '.join(o['params']['markets'])} | {o['latency_seconds']:.2f}s | "
                  f"${o['realized_pnl']:+,.2f} | {fmt(o['pnl_per_buy_pct'])} | {fmt(o['win_rate_pct'], 1)} | "
                  f"${o['buy_usdc']:,.0f} | {o['maker_fills']} / {o['taker_fills']} | ${o['fees']:.2f} |" for o in outs]
            L += ["", f"Forecast quality (log-loss): {ll}"]
            (rep / f"live_paper_compare{self.tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
            save_json([{k: o[k] for k in o if k != "markets"} for o in outs], rep / f"live_paper_compare{self.tag}.json")
        return outs


def load_params(cfg: dict, use_calibrated: bool = True) -> StrategyParams:
    cal = load_json(Path(cfg["paths"]["data_dir"]) / "calibrated_params.json") if use_calibrated else None
    if cal and cal.get("params"):
        return StrategyParams(**cal["params"])
    return StrategyParams.from_cfg(cfg)


def _parse_value(v):
    if isinstance(v, str):
        if v in ("true", "false"):
            return v == "true"
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def build_variants(cfg: dict, base: StrategyParams, spec: list) -> list:
    """spec: [{"name": str, "params_file": optional path to a calibrated_params*.json, "set": {param: value},
    "latency": seconds (optional), "interval": seconds (optional)}, ...]"""
    out = []
    for item in spec:
        d = base.as_dict()
        if item.get("params_file"):
            cal = load_json(Path(item["params_file"]))
            if not cal or not cal.get("params"):
                raise SystemExit(f"variant {item['name']}: cannot read params from {item['params_file']}")
            d.update(cal["params"])
        d.update({k: _parse_value(v) for k, v in (item.get("set") or {}).items()})
        v = {"name": item["name"], "params": StrategyParams(**d)}
        for k in ("latency", "interval"):
            if k in item:
                v[k] = float(item[k])
        out.append(v)
    return out


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    ap = argparse.ArgumentParser(description="Live PAPER trading of the strategy replica (no real orders)")
    ap.add_argument("--minutes", type=float, default=60, help="minutes to open new markets; then wait for settlement")
    ap.add_argument("--settle-wait", type=float, default=15.0, help="max minutes to wait for open markets to resolve")
    ap.add_argument("--config-params", action="store_true", help="ignore data/calibrated_params.json")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a strategy parameter for all variants, e.g. --set take_enabled=false")
    ap.add_argument("--variants", help="JSON file with strategy variants run side by side on the same feed")
    ap.add_argument("--tick", type=float, default=1.0, help="main loop period in seconds (<=1; fast variants need less)")
    ap.add_argument("--record", action="store_true", help="record spot, Chainlink, trade prints and top-5 books to data/recordings/*.jsonl.gz")
    ap.add_argument("--tag", default="", help="suffix for state/fills/report files (parallel runs)")
    ap.add_argument("--interim-report", type=float, default=30.0,
                    help="rewrite the reports every N minutes while running (0 = only at the end)")
    args = ap.parse_args(argv)
    # CI runners stop jobs with SIGTERM: turn it into KeyboardInterrupt so the final report is still written
    signal.signal(signal.SIGTERM, _raise_interrupt)
    cfg = load_config()
    global log
    log = setup_logging(cfg, "live_paper" + (f"_{args.tag}" if args.tag else ""))
    params = load_params(cfg, not args.config_params)
    if args.set:
        d = params.as_dict()
        for kv in args.set:
            k, v = kv.split("=", 1)
            d[k] = _parse_value(v)
        params = StrategyParams(**d)
    variants = build_variants(cfg, params, json.loads(Path(args.variants).read_text())) if args.variants else params
    bot = LiveStrategyPaperBot(cfg, variants, args.tag, record=args.record, tick_seconds=args.tick,
                               interim_report_seconds=args.interim_report * 60)
    outs = bot.run(args.minutes, args.settle_wait)
    print(json.dumps([{k: v for k, v in o.items() if k not in ("markets", "params")} for o in outs],
                     indent=1, default=str))


if __name__ == "__main__":
    main()
