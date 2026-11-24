#!/usr/bin/env python3
"""Real order latency and fill-rate test for Polymarket BTC "Up or Down" markets (CLOB V2).

Uses the official unified SDK `polymarket-client` (the legacy py-clob-client signs V1 orders, which the
CLOB rejects since the April 2026 V2 upgrade).

Modes
  --probe (default; no keys, no orders)
      geoblock check, clock offset, REST round trips to the CLOB, websocket feed lag (Polymarket market
      channel + Binance futures bookTicker), local order build+sign time with a throwaway key
      (orders are signed but NEVER posted).
  --live (real money, tiny size)
      needs POLYMARKET_PRIVATE_KEY + POLYMARKET_WALLET_ADDRESS (environment or .env), --i-accept-real-money,
      a location that is not geoblocked and a budget <= $50 (default $15). Phases:
        A latency  : post-only bid >= 15 cents below the best bid (cannot realistically fill) ->
                     time until it is visible in the public book -> cancel -> time until it is gone
        B maker    : post-only bid joining the best bid for --hold seconds; real fill vs the paper queue
                     model (queue position) and the optimistic paper model (always first in queue)
        C taker    : FAK buy of --taker-usd capped at the displayed best ask; real fill ratio and price
      All open orders are cancelled on exit (also on Ctrl+C / errors). Filled shares are held to resolution.

Outputs: reports/order_latency_<mode>_<tag>.{json,md}; live mode also writes variants/measured_<tag>.json
(variants/v3.json with the measured latencies) for live_paper.py.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import signal
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Optional

import requests
import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import TF_SECONDS  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"
CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GEOBLOCK = "https://polymarket.com/api/geoblock"
FUT_WS = "wss://fstream.binance.com/ws/btcusdt@bookTicker"
TIME_URLS = ["https://fapi.binance.com/fapi/v1/time", "https://api.binance.com/api/v3/time",
             "https://data-api.binance.vision/api/v3/time"]
MAX_BUDGET = 50.0          # hard cap, cannot be raised from the command line
MAX_SHARES = 10.0          # hard cap per order
PAPER = {"latency_s": 0.3, "cancel_latency_s": 0.2, "taker_fill_rate": 1.0}   # assumptions of variants/v3.json
FATAL_CODES = {"not_enough_balance", "invalid_nonce", "post_only_mode", "unknown"}


# ---------------------------------------------------------------------------------------------------- helpers
def stats(xs) -> dict:
    v = sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
    if not v:
        return {"n": 0}
    q = lambda p: v[min(len(v) - 1, int(round(p * (len(v) - 1))))]  # noqa: E731
    return {"n": len(v), "median": q(0.5), "p10": q(0.1), "p75": q(0.75), "p90": q(0.9), "max": v[-1],
            "mean": sum(v) / len(v)}


def load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); never overrides variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def geoblock(sess: requests.Session) -> dict:
    try:
        return sess.get(GEOBLOCK, timeout=10).json()
    except (requests.RequestException, ValueError) as exc:
        return {"blocked": None, "error": str(exc)}


def clock_offset_ms(sess: requests.Session, n: int = 12) -> dict:
    """server_ms ~= local_ms + offset (Binance server clock, best of n by round trip)."""
    best = None
    for url in TIME_URLS:
        for _ in range(n):
            t0 = time.time() * 1000
            try:
                srv = float(sess.get(url, timeout=5).json()["serverTime"])
            except (requests.RequestException, ValueError, KeyError):
                break
            t1 = time.time() * 1000
            if best is None or t1 - t0 < best[0]:
                best = (t1 - t0, srv - (t0 + t1) / 2, url)
        if best:
            break
    if not best:
        return {"offset_ms": 0.0, "rtt_ms": None, "source": None}
    return {"offset_ms": round(best[1], 1), "rtt_ms": round(best[0], 1), "source": best[2]}


def fetch_market(sess: requests.Session, tf: str, min_left: float = 0.0, now: Optional[float] = None) -> Optional[dict]:
    """Current (or next) BTC Up/Down market of timeframe tf with at least min_left seconds to go."""
    now = time.time() if now is None else now
    sec = TF_SECONDS[tf]
    start = int(now) - int(now) % sec
    for s in (start, start + sec):
        if s + sec - now < min_left:
            continue
        try:
            res = sess.get(GAMMA, params={"slug": f"btc-updown-{tf}-{s}"}, timeout=15).json()
        except (requests.RequestException, ValueError):
            return None
        if not res or not res[0].get("acceptingOrders"):
            continue
        m = res[0]
        return {"slug": m["slug"], "condition_id": m["conditionId"], "tokens": json.loads(m["clobTokenIds"]),
                "outcomes": json.loads(m.get("outcomes") or '["Up","Down"]'), "window_start": s,
                "window_end": s + sec, "tick": float(m.get("orderPriceMinTickSize") or 0.01),
                "min_size": float(m.get("orderMinSize") or 5),
                "fee_rate": float((m.get("feeSchedule") or {}).get("rate", 0) or 0)}
    return None


def paper_maker_fill(prints, i: int, price: float, ahead: float, size: float, t_from_ms: float,
                     t_to_ms: float) -> tuple[float, float]:
    """Paper fill of a resting BUY on outcome i at `price` between two exchange times (ms).
    prints: (t_local, ts_ex_ms, outcome, taker_side, px, size). A taker SELL of outcome i at px hits bids on i
    at px; a taker BUY of the other outcome at px hits bids on i at 1-px (complementary match).
    Returns (queue_model, front_of_queue_model) filled shares: the queue model first consumes the size that was
    resting ahead of us (cancellations ahead are ignored -> conservative); front_of_queue fills on any print."""
    q_fill = f_fill = 0.0
    for _, ts, oi, side, px, sz in prints:
        if ts < t_from_ms or ts > t_to_ms:
            continue
        hit_i, p = (oi, px) if side == "SELL" else (1 - oi, round(1.0 - px, 6))
        if hit_i != i:
            continue
        if p < price - 1e-9:                       # traded through our price: everything at our level filled
            q_fill = f_fill = size
        elif abs(p - price) < 1e-9:
            f_fill = min(size, f_fill + sz)
            take = sz - ahead
            ahead = max(ahead - sz, 0.0)
            if take > 0:
                q_fill = min(size, q_fill + take)
    return q_fill, f_fill


class Budget:
    def __init__(self, limit: float):
        self.limit = min(float(limit), MAX_BUDGET)
        self.spent = 0.0

    def can(self, worst_case: float) -> bool:
        return self.spent + worst_case <= self.limit + 1e-9

    def spend(self, usd: float) -> None:
        self.spent += max(float(usd), 0.0)


# ---------------------------------------------------------------------------------------------------- feeds
class BookFeed:
    """Polymarket market-channel websocket for one market: books, level changes, prints, mids, feed lag."""

    def __init__(self, meta: dict, offset_ms: float):
        self.meta, self.toks, self.off = meta, meta["tokens"], offset_ms
        self.books = [{"bids": {}, "asks": {}} for _ in self.toks]
        self.levels: dict[tuple, list] = defaultdict(list)     # (i, side, px) -> [(t_local, ts_ex, size)]
        self.prints: deque = deque(maxlen=100000)              # (t_local, ts_ex, i, side, px, size)
        self.mids: list[list] = [[] for _ in self.toks]        # [(t_local, mid)]
        self.lags: deque = deque(maxlen=200000)                # local receive - exchange timestamp (ms)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self._stop = False
        self.app = None

    def start(self) -> "BookFeed":
        def on_open(ws):
            ws.send(json.dumps({"assets_ids": self.toks, "type": "market"}))

        def runner():
            while not self._stop:
                self.app = websocket.WebSocketApp(CLOB_WS, on_open=on_open,
                                                  on_message=lambda _w, msg: self.on_message(msg))
                self.app.run_forever(ping_interval=10, ping_timeout=5)
                if not self._stop:
                    time.sleep(1)

        threading.Thread(target=runner, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop = True
        if self.app:
            try:
                self.app.close()
            except Exception:  # noqa: BLE001
                pass

    def on_message(self, msg: str, t_local: Optional[float] = None) -> None:
        t_local = time.time() if t_local is None else t_local
        try:
            data = json.loads(msg)
        except ValueError:
            return
        for e in (data if isinstance(data, list) else [data]):
            if isinstance(e, dict):
                self._on_event(e, t_local)

    def _on_event(self, e: dict, t_local: float) -> None:
        et, ts = e.get("event_type"), e.get("timestamp")
        ts = float(ts) if ts not in (None, "") else None
        if ts:
            self.lags.append(t_local * 1000 + self.off - ts)
        with self.lock:
            touched = set()
            if et == "book" and e.get("asset_id") in self.toks:
                i = self.toks.index(e["asset_id"])
                self.books[i]["bids"] = {float(x["price"]): float(x["size"]) for x in e.get("bids", e.get("buys", []))}
                self.books[i]["asks"] = {float(x["price"]): float(x["size"]) for x in e.get("asks", e.get("sells", []))}
                touched.add(i)
                self.ready.set()
            elif et == "price_change":
                for ch in e.get("price_changes", []):
                    if ch.get("asset_id") not in self.toks:
                        continue
                    i = self.toks.index(ch["asset_id"])
                    side = "bids" if ch.get("side") == "BUY" else "asks"
                    px, sz = round(float(ch["price"]), 4), float(ch["size"])
                    if sz <= 0:
                        self.books[i][side].pop(px, None)
                    else:
                        self.books[i][side][px] = sz
                    self.levels[(i, side, px)].append((t_local, ts, sz))
                    touched.add(i)
            elif et == "last_trade_price" and e.get("asset_id") in self.toks:
                self.prints.append((t_local, ts, self.toks.index(e["asset_id"]), e.get("side"),
                                    round(float(e["price"]), 4), float(e["size"])))
            for i in touched:
                m = self._mid(i)
                if m is not None and (not self.mids[i] or self.mids[i][-1][1] != m):
                    self.mids[i].append((t_local, m))

    def _mid(self, i: int) -> Optional[float]:
        b, a = self.books[i]["bids"], self.books[i]["asks"]
        return round((max(b) + min(a)) / 2, 5) if b and a else None

    def best_bid(self, i: int) -> Optional[float]:
        with self.lock:
            return max(self.books[i]["bids"]) if self.books[i]["bids"] else None

    def best_ask(self, i: int) -> Optional[float]:
        with self.lock:
            return min(self.books[i]["asks"]) if self.books[i]["asks"] else None

    def level(self, i: int, side: str, px: float) -> float:
        with self.lock:
            return self.books[i][side].get(round(px, 4), 0.0)

    def mid_at(self, i: int, t_local: float) -> Optional[float]:
        last = None
        for t, m in self.mids[i]:
            if t > t_local:
                break
            last = m
        return last

    def wait_level(self, i: int, side: str, px: float, pred: Callable[[float], bool], after: float,
                   timeout: float) -> Optional[tuple[float, Optional[float]]]:
        """First change of level (i, side, px) received after local time `after` whose new size satisfies pred."""
        key, end = (i, side, round(px, 4)), time.time() + timeout
        while True:
            with self.lock:
                for t, ts, sz in self.levels.get(key, ()):
                    if t >= after and pred(sz):
                        return t, ts
            if time.time() >= end:
                return None
            time.sleep(0.002)


class FuturesLag:
    """Binance futures bookTicker: local receive time - event time (ms)."""

    def __init__(self, offset_ms: float):
        self.off, self.lags, self._stop, self.app = offset_ms, deque(maxlen=200000), False, None

    def start(self) -> "FuturesLag":
        def on_msg(_w, msg):
            t = time.time() * 1000
            try:
                self.lags.append(t + self.off - float(json.loads(msg)["E"]))
            except (ValueError, KeyError):
                pass

        def runner():
            while not self._stop:
                self.app = websocket.WebSocketApp(FUT_WS, on_message=on_msg)
                self.app.run_forever(ping_interval=20, ping_timeout=10)
                if not self._stop:
                    time.sleep(2)

        threading.Thread(target=runner, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop = True
        if self.app:
            self.app.close()


# ---------------------------------------------------------------------------------------------------- probe
def throwaway_client():
    """SDK client with a random key and fake API credentials: it can build and sign orders (public market
    metadata is fetched) but cannot post anything. Used only to time local order preparation."""
    from eth_account import Account
    from polymarket import SecureClient
    from polymarket.models.clob.api_key import ApiKeyCreds
    acct = Account.create()
    creds = ApiKeyCreds.model_validate({"apiKey": str(uuid.uuid4()), "passphrase": uuid.uuid4().hex,
                                        "secret": base64.urlsafe_b64encode(os.urandom(32)).decode()})
    return SecureClient._create(private_key=acct.key.hex(), wallet=acct.address, credentials=creds,
                                validate_credentials=False)


def run_probe(args, log=print) -> dict:
    sess = requests.Session()
    out: dict = {"mode": "probe", "started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    out["geoblock"] = geoblock(sess)
    log(f"geoblock: {out['geoblock']}")
    out["clock"] = clock_offset_ms(sess)
    off = out["clock"]["offset_ms"]
    log(f"clock offset vs {out['clock']['source']}: {off} ms (rtt {out['clock']['rtt_ms']} ms)")

    metas = {tf: fetch_market(sess, tf, 30) for tf in ("15m", "5m")}
    metas = {k: v for k, v in metas.items() if v}
    if not metas:
        raise SystemExit("no active BTC Up/Down market found")
    tok = next(iter(metas.values()))["tokens"][0]
    cold = requests.Session()
    t = time.time()
    cold.get(f"{CLOB}/time", timeout=10)
    out["rest_cold_connect_ms"] = round((time.time() - t) * 1000, 1)
    rtt = defaultdict(list)
    for _ in range(args.rest_n):
        for name, url, params in (("GET /time", f"{CLOB}/time", None), ("GET /book", f"{CLOB}/book", {"token_id": tok})):
            t = time.time()
            try:
                cold.get(url, params=params, timeout=10)
                rtt[name].append((time.time() - t) * 1000)
            except requests.RequestException:
                pass
        time.sleep(0.2)
    out["rest_rtt_ms"] = {k: stats(v) for k, v in rtt.items()}
    log(f"REST: cold {out['rest_cold_connect_ms']} ms, " +
        ", ".join(f"{k} median {v.get('median', 0):.0f} ms" for k, v in out["rest_rtt_ms"].items()))

    sign = []
    try:
        c = throwaway_client()
        for k in range(args.rest_n):
            t = time.perf_counter()
            c.create_limit_order(asset_id=tok, price="0.01", size="5", side="BUY", post_only=True)
            sign.append((time.perf_counter() - t) * 1000)
        c.close()
        out["sign_first_ms"] = round(sign[0], 1)
        out["sign_ms"] = stats(sign[1:])
        log(f"order build+sign: first {sign[0]:.0f} ms (fetches market metadata), then median "
            f"{out['sign_ms']['median']:.1f} ms")
    except Exception as exc:  # noqa: BLE001
        out["sign_error"] = repr(exc)
        log(f"signing test failed: {exc!r}")

    active = {tf: BookFeed(m, off).start() for tf, m in metas.items()}   # timeframe -> current feed
    done: list = []
    fut = FuturesLag(off).start()
    log(f"measuring websocket lag for {args.minutes} min ...")
    end = time.time() + args.minutes * 60
    while time.time() < end:
        time.sleep(1)
        for tf, f in list(active.items()):
            if time.time() > f.meta["window_end"] - 2:
                f.stop()
                done.append(active.pop(tf))
                nm = fetch_market(sess, tf, 30)
                if nm:
                    active[tf] = BookFeed(nm, off).start()
    for f in active.values():
        f.stop()
    fut.stop()
    poly = [x for f in list(active.values()) + done for x in f.lags]
    out["ws_lag_ms"] = {"polymarket_market_channel": stats(poly), "binance_futures_bookTicker": stats(fut.lags)}
    out["ws_messages"] = {"polymarket": len(poly), "binance_futures": len(fut.lags)}
    log(f"WS lag: polymarket {out['ws_lag_ms']['polymarket_market_channel']}, "
        f"binance futures {out['ws_lag_ms']['binance_futures_bookTicker']}")
    book_rtt = out["rest_rtt_ms"].get("GET /book", {}).get("median")
    parts = [out["ws_lag_ms"]["polymarket_market_channel"].get("median"), out.get("sign_ms", {}).get("median"),
             (book_rtt / 2) if book_rtt else None]
    out["estimate_decision_to_exchange_ms"] = round(sum(p for p in parts if p is not None), 1) \
        if all(p is not None for p in parts) else None
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return out


# ---------------------------------------------------------------------------------------------------- live
class LiveTester:
    def __init__(self, client, args, offset_ms: float, log=print, sess=None,
                 market_fn=fetch_market, feed_cls=BookFeed, sleep=time.sleep):
        self.c, self.args, self.off, self.log = client, args, offset_ms, log
        self.sess = sess or requests.Session()
        self.market_fn, self.feed_cls, self.sleep = market_fn, feed_cls, sleep
        self.budget = Budget(args.budget)
        self.size = min(max(float(args.size), 0.0), MAX_SHARES)
        self.records: dict[str, list] = {"latency": [], "maker": [], "taker": [], "errors": []}
        self.open_ids: set = set()
        self.feed = None
        self.old_feeds: list = []
        self.stop_reason: Optional[str] = None

    # ---- market session
    def session(self, min_left: float):
        if self.feed is None or time.time() > self.feed.meta["window_end"] - min_left:
            meta = self.market_fn(self.sess, self.args.tf, min_left)
            if not meta:
                return None, None
            if self.feed is not None:
                self.feed.stop()
                self.old_feeds.append(self.feed)
            self.feed = self.feed_cls(meta, self.off).start()
            self.feed.ready.wait(15)
            try:   # warm the SDK's market metadata cache so the first timed order is not penalised
                self.c.create_limit_order(asset_id=meta["tokens"][0], price=str(meta["tick"]), size=str(self.size),
                                          side="BUY", post_only=True)
            except Exception as exc:  # noqa: BLE001
                self.log(f"warm-up sign failed: {exc!r}")
            self.log(f"market {meta['slug']} (ends {time.strftime('%H:%M:%S', time.gmtime(meta['window_end']))} UTC)")
        return self.feed.meta, self.feed

    def ex_ms(self, t_local: float) -> float:
        return t_local * 1000 + self.off

    def _rejected(self, phase: str, resp) -> bool:
        """Record a rejected order; returns True if the run must stop."""
        self.records["errors"].append({"phase": phase, "code": resp.code, "message": resp.message})
        self.log(f"{phase}: rejected {resp.code}: {resp.message}")
        if resp.code in FATAL_CODES:
            self.stop_reason = f"{phase}: {resp.code}"
            return True
        return False

    def _cancel(self, oid: str):
        t = time.time()
        r = self.c.cancel_order(order_id=oid)
        t2 = time.time()
        if oid in r.canceled:
            self.open_ids.discard(oid)
        return r, t, t2

    def matched(self, oid: str) -> float:
        try:
            return float(self.c.get_order(order_id=oid).size_matched)
        except Exception:  # noqa: BLE001  (order no longer queryable -> rely on trades)
            return 0.0

    def fills(self, oid: str, meta: dict) -> list[dict]:
        out = []
        try:
            for tr in self.c.list_account_trades(market=meta["condition_id"]).iter_items():
                for mo in tr.maker_orders:
                    if mo.order_id == oid:
                        out.append({"t": tr.matched_at.timestamp(), "price": float(mo.price),
                                    "size": float(mo.matched_amount), "role": "maker"})
                if tr.taker_order_id == oid:
                    out.append({"t": tr.matched_at.timestamp(), "price": float(tr.price), "size": float(tr.size),
                                "role": "taker", "fee_rate_bps": float(tr.fee_rate_bps)})
        except Exception as exc:  # noqa: BLE001
            self.log(f"trade lookup failed: {exc!r}")
        return out

    def cancel_all(self) -> None:
        for _ in range(3):
            try:
                self.c.cancel_all()
                self.open_ids.clear()
                return
            except Exception as exc:  # noqa: BLE001
                self.log(f"cancel_all failed ({exc!r}), retrying")
                time.sleep(1)

    # ---- phase A: placement / cancel latency with an order that cannot realistically fill
    def run_latency(self, n: int) -> None:
        k = 0
        while k < n and not self.stop_reason:
            meta, feed = self.session(min_left=90)
            if not meta:
                self.sleep(5)
                continue
            i, tick = k % 2, meta["tick"]
            bb = feed.best_bid(i)
            if bb is None or bb - 0.15 < tick:
                self.sleep(1)
                k += 1
                continue
            cands = [round(tick * j, 4) for j in range(int(round((bb - 0.15) / tick)), 0, -1)]
            px = next((p for p in cands if feed.level(i, "bids", p) == 0), cands[0])
            size = max(self.size, meta["min_size"])
            if not self.budget.can(size * px):
                self.stop_reason = "budget"
                break
            before = feed.level(i, "bids", px)
            rec = {"market": meta["slug"], "outcome": meta["outcomes"][i], "price": px, "size": size,
                   "level_before": before}
            t0 = time.time()
            signed = self.c.create_limit_order(asset_id=meta["tokens"][i], price=str(px), size=str(size),
                                               side="BUY", post_only=True)
            t1 = time.time()
            resp = self.c.post_order(signed)
            t2 = time.time()
            rec.update(sign_ms=(t1 - t0) * 1000, post_rtt_ms=(t2 - t1) * 1000)
            if not resp.ok:
                k += 1
                if self._rejected("latency", resp):
                    break
                continue
            oid = resp.order_id
            self.open_ids.add(oid)
            rec["status"] = resp.status
            vis = feed.wait_level(i, "bids", px, lambda s: s >= before + size - 1e-6, t1, 5.0)
            if vis:
                rec.update(visible_after_send_ms=(vis[0] - t1) * 1000,
                           exchange_live_after_decision_ms=(vis[1] - self.ex_ms(t0)) if vis[1] else None)
            self.sleep(0.5)
            lvl = feed.level(i, "bids", px)
            r, t3, t4 = self._cancel(oid)
            rec.update(cancel_rtt_ms=(t4 - t3) * 1000, cancel_ok=oid in r.canceled,
                       cancel_reason=r.not_canceled.get(oid))
            gone = feed.wait_level(i, "bids", px, lambda s: s <= lvl - size + 1e-6, t3, 5.0)
            if gone:
                rec.update(gone_after_send_ms=(gone[0] - t3) * 1000,
                           exchange_dead_after_decision_ms=(gone[1] - self.ex_ms(t3)) if gone[1] else None)
            if not rec["cancel_ok"]:
                m = self.matched(oid)
                rec["filled"] = m
                self.budget.spend(m * px)
            self.records["latency"].append(rec)
            self.log("latency %d/%d: sign %.1f ms, post %.0f ms, visible %s ms, cancel %.0f ms, gone %s ms" % (
                k + 1, n, rec["sign_ms"], rec["post_rtt_ms"], _f(rec.get("visible_after_send_ms")),
                rec["cancel_rtt_ms"], _f(rec.get("gone_after_send_ms"))))
            k += 1
            self.sleep(1.5)

    # ---- phase B: maker fill rate at the best bid vs the paper models
    def run_maker(self, n: int, hold: float) -> None:
        k = 0
        while k < n and not self.stop_reason:
            dur = TF_SECONDS[self.args.tf]
            meta, feed = self.session(min_left=hold + 0.2 * dur + 20)
            if not meta:
                self.sleep(5)
                continue
            i, tick = k % 2, meta["tick"]
            bb, ba = feed.best_bid(i), feed.best_ask(i)
            if bb is None or ba is None or not (0.10 <= bb <= 0.90) or ba - bb < tick - 1e-9:
                self.sleep(1)
                continue
            size = max(self.size, meta["min_size"])
            if not self.budget.can(size * bb):
                self.stop_reason = "budget"
                break
            ahead = feed.level(i, "bids", bb)
            rec = {"market": meta["slug"], "outcome": meta["outcomes"][i], "price": bb, "size": size,
                   "queue_ahead": ahead, "spread": round(ba - bb, 4)}
            t0 = time.time()
            signed = self.c.create_limit_order(asset_id=meta["tokens"][i], price=str(bb), size=str(size),
                                               side="BUY", post_only=True)
            t1 = time.time()
            resp = self.c.post_order(signed)
            t2 = time.time()
            if not resp.ok:
                k += 1
                if self._rejected("maker", resp):
                    break
                continue
            oid = resp.order_id
            self.open_ids.add(oid)
            vis = feed.wait_level(i, "bids", bb, lambda s: s >= ahead + size - 1e-6, t1, 3.0)
            t_live = vis[1] if vis and vis[1] else self.ex_ms(t2)
            stop_at = min(t2 + hold, meta["window_end"] - 0.2 * dur)
            filled = 0.0
            while time.time() < stop_at:
                self.sleep(1.0)
                filled = self.matched(oid)
                if filled >= size - 1e-9:
                    break
            t_end = self.ex_ms(time.time())
            if filled < size - 1e-9:
                _r, t3, t4 = self._cancel(oid)
                t_end = self.ex_ms((t3 + t4) / 2)        # ~ when the cancel reached the exchange
                rec["cancel_rtt_ms"] = (t4 - t3) * 1000
                filled = max(filled, self.matched(oid))
            with feed.lock:
                prints = list(feed.prints)
            q_fill, f_fill = paper_maker_fill(prints, i, bb, ahead, size, t_live, t_end)
            fl = self.fills(oid, meta)
            filled = max(filled, sum(f["size"] for f in fl))
            self.budget.spend(filled * bb)
            rec.update(order_id=oid, decision_to_ack_ms=(t2 - t0) * 1000, post_rtt_ms=(t2 - t1) * 1000, held_s=round((t_end - t_live) / 1000, 2),
                       real_filled=filled, paper_queue_filled=q_fill, paper_front_filled=f_fill,
                       first_fill_t=min((f["t"] for f in fl), default=None), t_live_ms=t_live, t_post=t2,
                       outcome_index=i, slug=meta["slug"])
            self.records["maker"].append(rec)
            self.log("maker %d/%d: bid %.2f x %.0f (ahead %.0f) -> real %.1f, paper queue %.1f, paper front %.1f" % (
                k + 1, n, bb, size, ahead, filled, q_fill, f_fill))
            k += 1
            self.sleep(2)

    # ---- phase C: taker fill ratio / price vs the displayed ask
    def run_taker(self, n: int, usd: float) -> None:
        k = 0
        while k < n and not self.stop_reason:
            meta, feed = self.session(min_left=60)
            if not meta:
                self.sleep(5)
                continue
            i = k % 2
            ba = feed.best_ask(i)
            if ba is None or not (0.05 <= ba <= 0.95):
                self.sleep(1)
                continue
            if not self.budget.can(usd * 1.05):
                self.stop_reason = "budget"
                break
            rec = {"market": meta["slug"], "outcome": meta["outcomes"][i], "ask": ba,
                   "ask_size": feed.level(i, "asks", ba), "usd": usd}
            t0 = time.time()
            try:
                signed = self.c.create_market_order(asset_id=meta["tokens"][i], side="BUY", amount=str(usd),
                                                    max_price=str(ba), order_type="FAK")
            except Exception as exc:  # noqa: BLE001  (e.g. InsufficientLiquidityError)
                self.records["errors"].append({"phase": "taker", "code": type(exc).__name__, "message": str(exc)})
                k += 1
                continue
            t1 = time.time()
            resp = self.c.post_order(signed)
            t2 = time.time()
            rec.update(sign_ms=(t1 - t0) * 1000, post_rtt_ms=(t2 - t1) * 1000,
                       ask_after=feed.best_ask(i))
            want = usd / ba
            if not resp.ok:
                rec.update(status=resp.code, shares=0.0, fill_ratio=0.0)
                if resp.code != "fak_not_filled" and self._rejected("taker", resp):
                    self.records["taker"].append(rec)
                    break
            else:
                spent, shares = float(resp.making_amount), float(resp.taking_amount)
                if resp.status == "delayed":
                    self.sleep(3)
                    fl = self.fills(resp.order_id, meta)
                    shares = sum(f["size"] for f in fl)
                    spent = sum(f["size"] * f["price"] for f in fl)
                rec.update(status=resp.status, order_id=resp.order_id, shares=shares, spent=spent,
                           avg_price=(spent / shares) if shares else None,
                           fill_ratio=min(shares / want, 1.0) if want else 0.0)
                self.budget.spend(spent * 1.03)
                with feed.lock:   # our own print on the public feed: taker BUY of outcome i with our size
                    pr = [p for p in feed.prints if p[2] == i and p[3] == "BUY" and p[0] >= t1 and p[1]
                          and abs(p[5] - shares) < 0.05]
                if pr:
                    rec["exchange_match_after_decision_ms"] = pr[0][1] - self.ex_ms(t0)
            self.records["taker"].append(rec)
            self.log("taker %d/%d: ask %.2f -> %s, %.2f shares (fill %.0f%%), %.0f ms" % (
                k + 1, n, ba, rec.get("status"), rec.get("shares", 0), 100 * rec.get("fill_ratio", 0),
                rec["post_rtt_ms"]))
            k += 1
            self.sleep(3)

    def markouts(self) -> None:
        feeds = {f.meta["slug"]: f for f in self.old_feeds + ([self.feed] if self.feed else [])}
        for rec in self.records["maker"]:
            if rec["real_filled"] <= 0 and rec["paper_front_filled"] <= 0:
                continue
            f = feeds.get(rec["slug"])
            t = rec["first_fill_t"] or rec["t_post"]
            for h in (5, 30):
                m = f.mid_at(rec["outcome_index"], t + h) if f else None
                rec[f"markout_{h}s_cents"] = round((m - rec["price"]) * 100, 2) if m is not None else None

    def summary(self) -> dict:
        lat, mk, tk = self.records["latency"], self.records["maker"], self.records["taker"]
        s = {"latency": {k: stats(r.get(k) for r in lat) for k in
                         ("sign_ms", "post_rtt_ms", "visible_after_send_ms", "exchange_live_after_decision_ms",
                          "cancel_rtt_ms", "gone_after_send_ms", "exchange_dead_after_decision_ms")},
             "maker": {"orders": len(mk), "shares": sum(r["size"] for r in mk),
                       "real_fill_rate": _ratio(mk, "real_filled"),
                       "paper_queue_fill_rate": _ratio(mk, "paper_queue_filled"),
                       "paper_front_fill_rate": _ratio(mk, "paper_front_filled"),
                       "markout_5s_cents": stats(r.get("markout_5s_cents") for r in mk if r["real_filled"] > 0),
                       "markout_30s_cents": stats(r.get("markout_30s_cents") for r in mk if r["real_filled"] > 0)},
             "taker": {"orders": len(tk), "fill_ratio": stats(r.get("fill_ratio") for r in tk),
                       "post_rtt_ms": stats(r.get("post_rtt_ms") for r in tk),
                       "price_vs_ask_cents": stats(((r["avg_price"] - r["ask"]) * 100) for r in tk if r.get("avg_price")),
                       "statuses": {st: sum(1 for r in tk if r.get("status") == st)
                                    for st in {r.get("status") for r in tk}}},
             "budget": {"limit": self.budget.limit, "spent_estimate": round(self.budget.spent, 2)},
             "stop_reason": self.stop_reason, "errors": len(self.records["errors"])}
        live = s["latency"]["exchange_live_after_decision_ms"]
        if not live.get("n"):
            live = {k: v + (s["latency"]["sign_ms"].get("median") or 0) if isinstance(v, float) else v
                    for k, v in s["latency"]["visible_after_send_ms"].items()}
        dead = s["latency"]["exchange_dead_after_decision_ms"]
        if not dead.get("n"):
            dead = s["latency"]["gone_after_send_ms"]
        s["measured_for_paper"] = {
            "latency_s": round(live["p75"] / 1000, 3) if live.get("n") else None,
            "cancel_latency_s": round(dead["p75"] / 1000, 3) if dead.get("n") else None,
            "taker_fill_rate": s["taker"]["fill_ratio"].get("mean"), "paper_assumptions": PAPER}
        return s


def _ratio(rows, key) -> Optional[float]:
    tot = sum(r["size"] for r in rows)
    return round(sum(r[key] for r in rows) / tot, 4) if tot else None


def _f(x) -> str:
    return "-" if x is None else f"{x:.0f}"


def write_measured_variants(measured: dict, tag: str) -> Optional[Path]:
    if not measured.get("latency_s"):
        return None
    src = json.loads((ROOT / "variants" / "v3.json").read_text())
    for v in src:
        if "latency" in v:
            v["latency"] = measured["latency_s"]
        if "cancel_latency" in v and measured.get("cancel_latency_s"):
            v["cancel_latency"] = measured["cancel_latency_s"]
    out = ROOT / "variants" / f"measured_{tag}.json"
    out.write_text(json.dumps(src, indent=1))
    return out


def run_live(args, log=print) -> dict:
    sess = requests.Session()
    geo = geoblock(sess)
    log(f"geoblock: {geo}")
    if geo.get("blocked") is not False:
        raise SystemExit(f"STOP: bu konumdan emir gönderilemez (Polymarket geoblock: {geo}). "
                         "Testi engelli olmayan bir ülkedeki kendi bilgisayarınızda çalıştırın.")
    if not args.i_accept_real_money:
        raise SystemExit("STOP: gerçek para kullanılır; onay için --i-accept-real-money ekleyin.")
    load_dotenv(ROOT / ".env")
    # same variables as the bot's live mode (POLY_*) are accepted as fallbacks
    pk = os.environ.get("POLYMARKET_PRIVATE_KEY") or os.environ.get("POLY_PRIVATE_KEY")
    wallet = os.environ.get("POLYMARKET_WALLET_ADDRESS") or os.environ.get("POLY_FUNDER_ADDRESS")
    if not pk or not wallet:
        raise SystemExit("STOP: POLYMARKET_PRIVATE_KEY ve POLYMARKET_WALLET_ADDRESS gerekli (ortam değişkeni veya .env; "
                         "POLY_PRIVATE_KEY / POLY_FUNDER_ADDRESS da kabul edilir).")
    from polymarket import SecureClient
    clock = clock_offset_ms(sess)
    log(f"clock offset {clock}")
    client = SecureClient.create(private_key=pk, wallet=wallet)
    try:
        bal = client.get_balance_allowance(asset_type="COLLATERAL").balance / 1e6
        log(f"balance: ${bal:.2f}")
        if bal < 2:
            raise SystemExit(f"STOP: bakiye çok düşük (${bal:.2f}).")
    except SystemExit:
        client.close()
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"balance check failed: {exc!r}")
    t = LiveTester(client, args, clock["offset_ms"], log=log, sess=sess)
    log(f"PLAN: {args.tf} BTC markets, latency x{args.latency_n} (no fill expected), maker x{args.maker_n} "
        f"({t.size:g} shares, hold {args.hold:g}s), taker x{args.taker_n} (${args.taker_usd:g}); "
        f"budget ${t.budget.limit:.2f}. Starting in {args.countdown}s - Ctrl+C to abort.")
    time.sleep(args.countdown)

    def _sig(*_a):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _sig)
    out = {"mode": "live", "started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "geoblock": geo,
           "clock": clock, "args": {k: v for k, v in vars(args).items()}}
    try:
        if args.latency_n:
            t.run_latency(args.latency_n)
        if args.maker_n and not t.stop_reason:
            t.run_maker(args.maker_n, args.hold)
        if args.taker_n and not t.stop_reason:
            t.run_taker(args.taker_n, args.taker_usd)
        last = max([r["t_post"] + r["held_s"] for r in t.records["maker"]] or [0])
        if time.time() < last + 31:
            time.sleep(last + 31 - time.time())
    except KeyboardInterrupt:
        t.stop_reason = "interrupted"
        log("interrupted")
    finally:
        t.cancel_all()
        for f in t.old_feeds + ([t.feed] if t.feed else []):
            f.stop()
        client.close()
    t.markouts()
    out.update(records=t.records, summary=t.summary(),
               finished=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    return out


# ---------------------------------------------------------------------------------------------------- report
def _row(name: str, st: dict, unit: str = "ms") -> str:
    if not st or not st.get("n"):
        return f"| {name} | - | - | - | 0 |"
    return f"| {name} | {st['median']:.1f} {unit} | {st['p90']:.1f} {unit} | {st['max']:.1f} {unit} | {st['n']} |"


def report_md(out: dict) -> str:
    L = [f"# Emir gecikmesi / dolum testi — {out['mode']}", "",
         f"Başlangıç {out['started']}, bitiş {out.get('finished')}. Konum: {out['geoblock'].get('country')}"
         f"-{out['geoblock'].get('region')} (Polymarket emir engeli: **{out['geoblock'].get('blocked')}**). "
         f"Saat farkı kaynağı: {out['clock'].get('source')} ({out['clock'].get('offset_ms')} ms).", ""]
    if out["mode"] == "probe":
        L += ["Bu ölçümde **emir gönderilmedi** (anahtarsız mod). Gerçek emir gecikmesi ve dolum oranı `--live` ile ölçülür.", "",
              "| ölçüm | medyan | p90 | maks | n |", "|---|---|---|---|---|",
              _row("CLOB GET /time gidiş-dönüş", out["rest_rtt_ms"].get("GET /time")),
              _row("CLOB GET /book gidiş-dönüş", out["rest_rtt_ms"].get("GET /book")),
              _row("emir hazırlama + imza (yerel)", out.get("sign_ms")),
              _row("Polymarket WS veri gecikmesi", out["ws_lag_ms"]["polymarket_market_channel"]),
              _row("Binance vadeli WS veri gecikmesi", out["ws_lag_ms"]["binance_futures_bookTicker"]), "",
              f"- İlk bağlantı (TLS) maliyeti: {out.get('rest_cold_connect_ms')} ms; bir markette ilk emir imzası "
              f"{out.get('sign_first_ms')} ms (market bilgisi indiriliyor → market açılınca önceden ısıtılmalı).",
              f"- Tahmini 'karar → emir borsada' süresi (WS gecikmesi + imza + yarım gidiş-dönüş): "
              f"**{out.get('estimate_decision_to_exchange_ms')} ms**. Bu bir tahmindir; borsanın emir işleme süresi dahil değildir.",
              "- Not: WS gecikmesi iki saat arasındaki farka dayanır (Binance saati referans); saat ölçümünün "
              f"gidiş-dönüşü {out['clock'].get('rtt_ms')} ms olduğundan hata payı en fazla "
              f"±{round((out['clock'].get('rtt_ms') or 0) / 2)} ms'dir. Yüksek p90/maks değerleri büyük olasılıkla kısa yoğunluk (mesaj yığılması) anlarından gelir."]
        return "\n".join(L) + "\n"
    s = out["summary"]
    lat, mk, tk, ms = s["latency"], s["maker"], s["taker"], s["measured_for_paper"]
    L += ["## A) Emir ve iptal gecikmesi (dolmayacak uzak teklif)", "",
          "| ölçüm | medyan | p90 | maks | n |", "|---|---|---|---|---|",
          _row("imza (yerel)", lat["sign_ms"]), _row("POST /order gidiş-dönüş (onay)", lat["post_rtt_ms"]),
          _row("gönderim → kitapta görünür (bizim WS)", lat["visible_after_send_ms"]),
          _row("karar → borsada canlı (borsa zaman damgası)", lat["exchange_live_after_decision_ms"]),
          _row("iptal isteği gidiş-dönüş", lat["cancel_rtt_ms"]),
          _row("iptal → kitaptan silindi (bizim WS)", lat["gone_after_send_ms"]),
          _row("iptal kararı → borsada silindi (borsa zaman damgası)", lat["exchange_dead_after_decision_ms"]), "",
          "## B) Pasif (maker) dolum oranı — en iyi alış fiyatına katılma", "",
          f"Emir: {mk['orders']}, toplam {mk['shares']:g} share.", "",
          "| model | dolum oranı |", "|---|---|",
          f"| **gerçek** | **{_pct(mk['real_fill_rate'])}** |",
          f"| paper — kuyruk modeli (önümüzdeki hacim önce dolar) | {_pct(mk['paper_queue_fill_rate'])} |",
          f"| paper — iyimser (hep kuyruğun başında) | {_pct(mk['paper_front_fill_rate'])} |", "",
          f"Dolumdan sonra fiyat değişimi (sent/share, + iyi): 5 sn {_st(mk['markout_5s_cents'])}, "
          f"30 sn {_st(mk['markout_30s_cents'])}.", "",
          "## C) Anlık alım (taker, FAK, gösterilen satış fiyatıyla sınırlı)", "",
          f"Emir: {tk['orders']}; durumlar: {tk['statuses']}; ortalama dolum oranı: {_pct(tk['fill_ratio'].get('mean'))}; "
          f"fiyat − gösterilen satış: {_st(tk['price_vs_ask_cents'])} sent; onay süresi {_st(tk['post_rtt_ms'])} ms.", "",
          "## Paper varsayımlarıyla karşılaştırma", "",
          "| parametre | paper (v3) | ölçülen (p75) |", "|---|---|---|",
          f"| karar → emir canlı | {PAPER['latency_s']} sn | {ms['latency_s']} sn |",
          f"| iptal gecikmesi | {PAPER['cancel_latency_s']} sn | {ms['cancel_latency_s']} sn |",
          f"| taker dolum oranı | %100 | {_pct(ms['taker_fill_rate'])} |", "",
          f"Bütçe: ${s['budget']['limit']:.2f}, tahmini harcanan ${s['budget']['spent_estimate']:.2f}. "
          f"Durma nedeni: {s['stop_reason'] or 'yok (tamamlandı)'}; reddedilen emir: {s['errors']}.",
          "Ölçülen değerlerle paper testi: `python3 live_paper.py --variants variants/measured_<etiket>.json ...`"]
    return "\n".join(L) + "\n"


def _pct(x) -> str:
    return "-" if x is None else f"%{100 * x:.1f}"


def _st(st: dict) -> str:
    return "-" if not st or not st.get("n") else f"medyan {st['median']:.2f} (n={st['n']})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="send REAL orders (tiny size, strict caps)")
    ap.add_argument("--i-accept-real-money", action="store_true")
    ap.add_argument("--tf", default="15m", choices=["5m", "15m"])
    ap.add_argument("--budget", type=float, default=15.0, help=f"USD, hard cap {MAX_BUDGET:g}")
    ap.add_argument("--size", type=float, default=5.0, help=f"shares per limit order (market minimum, cap {MAX_SHARES:g})")
    ap.add_argument("--latency-n", type=int, default=20)
    ap.add_argument("--maker-n", type=int, default=8)
    ap.add_argument("--hold", type=float, default=30.0)
    ap.add_argument("--taker-n", type=int, default=4)
    ap.add_argument("--taker-usd", type=float, default=1.0)
    ap.add_argument("--countdown", type=int, default=10)
    ap.add_argument("--minutes", type=float, default=3.0, help="probe: websocket measurement duration")
    ap.add_argument("--rest-n", type=int, default=20)
    ap.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M", time.gmtime()))
    args = ap.parse_args(argv)
    out = run_live(args) if args.live else run_probe(args)
    rep = ROOT / "reports" / f"order_latency_{out['mode']}_{args.tag}"
    rep.with_suffix(".json").write_text(json.dumps(out, indent=1, default=str))
    rep.with_suffix(".md").write_text(report_md(out))
    print(f"report: {rep.with_suffix('.md')}")
    if out["mode"] == "live":
        p = write_measured_variants(out["summary"]["measured_for_paper"], args.tag)
        if p:
            print(f"variants with measured latency: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
