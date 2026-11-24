"""Offline tests for tools/order_latency_test.py (fake SDK client + fake websocket, no network, no orders).
Run:  python tests/test_order_latency.py"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import order_latency_test as olt  # noqa: E402

META = {"slug": "btc-updown-15m-1", "condition_id": "0xc", "tokens": ["UP", "DOWN"], "outcomes": ["Up", "Down"],
        "window_start": 0, "window_end": time.time() + 3600, "tick": 0.01, "min_size": 5.0, "fee_rate": 0.05}


def args(**kw):
    a = dict(tf="15m", budget=15.0, size=5.0, latency_n=3, maker_n=2, hold=2.0, taker_n=2, taker_usd=1.0,
             countdown=0, i_accept_real_money=True)
    a.update(kw)
    return SimpleNamespace(**a)


class FakeFeed(olt.BookFeed):
    """BookFeed fed by FakeClient instead of a websocket."""
    instances: list = []

    def start(self):
        FakeFeed.instances.append(self)
        self._apply([{"event_type": "book", "asset_id": t, "timestamp": str(int(time.time() * 1000)),
                      "bids": [{"price": "0.50", "size": "100"}, {"price": "0.20", "size": "7"}],
                      "asks": [{"price": "0.52", "size": "80"}]} for t in self.toks])
        return self

    def stop(self):
        pass

    def _apply(self, events):
        self.on_message(json.dumps(events))


class FakeClient:
    """Mimics the polymarket SDK calls used by LiveTester; resting orders show up in the fake feed."""

    def __init__(self, feed_ref, fill_maker=0.0, reject=None, taker_fill=1.0):
        self.feed_ref, self.fill_maker, self.reject, self.taker_fill = feed_ref, fill_maker, reject, taker_fill
        self.orders: dict = {}
        self.cancel_all_calls = 0
        self.n = 0

    def _feed(self):
        return FakeFeed.instances[-1]

    def create_limit_order(self, *, asset_id, price, size, side, post_only):
        assert side == "BUY" and post_only
        return {"kind": "limit", "tok": asset_id, "price": float(price), "size": float(size)}

    def create_market_order(self, *, asset_id, side, amount, max_price, order_type):
        assert side == "BUY" and order_type == "FAK"
        return {"kind": "market", "tok": asset_id, "amount": float(amount), "max_price": float(max_price)}

    def post_order(self, o):
        self.n += 1
        if self.reject:
            return SimpleNamespace(ok=False, code=self.reject, message="fake reject")
        oid = f"o{self.n}"
        f = self._feed()
        i = f.toks.index(o["tok"])
        if o["kind"] == "market":
            shares = o["amount"] / o["max_price"] * self.taker_fill
            ts = str(int(time.time() * 1000))
            f._apply([{"event_type": "last_trade_price", "asset_id": o["tok"], "side": "BUY",
                       "price": str(o["max_price"]), "size": f"{shares:.4f}", "timestamp": ts}])
            return SimpleNamespace(ok=True, order_id=oid, status="matched", making_amount=shares * o["max_price"],
                                   taking_amount=shares)
        lvl = f.level(i, "bids", o["price"]) + o["size"]
        self.orders[oid] = dict(o, i=i, matched=0.0, live=True)
        threading.Timer(0.03, lambda: f._apply([{"event_type": "price_change", "timestamp": str(int(time.time() * 1000)),
                                                 "price_changes": [{"asset_id": o["tok"], "side": "BUY",
                                                                    "price": f"{o['price']:.2f}", "size": str(lvl)}]}])).start()
        if self.fill_maker:   # a taker sells into our bid shortly after
            def hit():
                self.orders[oid]["matched"] = min(o["size"], self.fill_maker)
                f._apply([{"event_type": "last_trade_price", "asset_id": o["tok"], "side": "SELL",
                           "price": f"{o['price']:.2f}", "size": "200", "timestamp": str(int(time.time() * 1000))}])
            threading.Timer(0.2, hit).start()
        return SimpleNamespace(ok=True, order_id=oid, status="live", making_amount=0, taking_amount=0)

    def cancel_order(self, *, order_id):
        o = self.orders[order_id]
        f = self._feed()
        o["live"] = False
        lvl = max(f.level(o["i"], "bids", o["price"]) - o["size"], 0.0)
        threading.Timer(0.02, lambda: f._apply([{"event_type": "price_change", "timestamp": str(int(time.time() * 1000)),
                                                 "price_changes": [{"asset_id": o["tok"], "side": "BUY",
                                                                    "price": f"{o['price']:.2f}", "size": str(lvl)}]}])).start()
        return SimpleNamespace(canceled=(order_id,), not_canceled={})

    def cancel_all(self):
        self.cancel_all_calls += 1
        for o in self.orders.values():
            o["live"] = False
        return SimpleNamespace(canceled=(), not_canceled={})

    def get_order(self, *, order_id):
        return SimpleNamespace(size_matched=self.orders[order_id]["matched"])

    def list_account_trades(self, **_kw):
        return SimpleNamespace(iter_items=lambda: iter(()))


def tester(client, **kw):
    FakeFeed.instances.clear()
    return olt.LiveTester(client, args(**kw), 0.0, log=lambda *_a: None,
                          market_fn=lambda *_a, **_k: dict(META), feed_cls=FakeFeed, sleep=lambda s: time.sleep(min(s, 0.05)))


# ------------------------------------------------------------------------------------------------------ tests
def test_stats_and_budget_caps():
    s = olt.stats([3, 1, 2, None, float("nan")])
    assert s["n"] == 3 and s["median"] == 2 and s["max"] == 3
    assert olt.stats([])["n"] == 0
    b = olt.Budget(1000)
    assert b.limit == olt.MAX_BUDGET
    assert b.can(50) and not b.can(50.01)
    b.spend(10)
    assert b.can(40) and not b.can(41)


def test_paper_maker_fill_models():
    # (t_local, ts_ex, outcome, taker_side, px, size); our bid: outcome 0 at 0.50, 10 ahead, size 5
    prints = [(0, 100, 0, "SELL", 0.50, 8),     # consumes 8 of the 10 ahead
              (0, 200, 1, "BUY", 0.50, 4),      # complementary: BUY Down @0.50 hits bids on Up @0.50 -> 2 ahead + 2 ours
              (0, 300, 1, "BUY", 0.49, 50),     # BUY Down @0.49 -> Up @0.51, above our bid: no effect
              (0, 999, 0, "SELL", 0.49, 1)]     # outside the window
    q, f = olt.paper_maker_fill(prints, 0, 0.50, 10.0, 5.0, 50, 400)
    assert math.isclose(q, 2.0) and math.isclose(f, 5.0)
    # a trade-through fills everything in both models
    q, f = olt.paper_maker_fill([(0, 100, 0, "SELL", 0.48, 1)], 0, 0.50, 1000.0, 5.0, 0, 400)
    assert q == f == 5.0
    assert olt.paper_maker_fill(prints, 0, 0.50, 10.0, 5.0, 1000, 2000) == (0.0, 0.0)


def test_bookfeed_parsing_and_wait_level():
    f = olt.BookFeed(dict(META), 0.0)
    now = time.time()
    f.on_message(json.dumps([{"event_type": "book", "asset_id": "UP", "timestamp": str(int(now * 1000) - 40),
                              "bids": [{"price": "0.45", "size": "10"}], "asks": [{"price": "0.47", "size": "5"}]}]),
                 t_local=now)
    assert f.best_bid(0) == 0.45 and f.best_ask(0) == 0.47 and f.level(0, "bids", 0.45) == 10
    assert 35 <= f.lags[-1] <= 45
    f.on_message(json.dumps({"event_type": "price_change", "timestamp": str(int(now * 1000) + 10), "price_changes": [
        {"asset_id": "UP", "side": "BUY", "price": "0.46", "size": "5"}]}), t_local=now + 0.02)
    assert f.best_bid(0) == 0.46 and f.mids[0][-1][1] == 0.465
    hit = f.wait_level(0, "bids", 0.46, lambda s: s >= 5, now, 0.1)
    assert hit and math.isclose(hit[0], now + 0.02) and hit[1] == int(now * 1000) + 10
    assert f.wait_level(0, "bids", 0.46, lambda s: s >= 6, now, 0.05) is None
    f.on_message(json.dumps({"event_type": "last_trade_price", "asset_id": "DOWN", "side": "BUY", "price": "0.54",
                             "size": "3", "timestamp": "1"}), t_local=now)
    assert f.prints[-1][2:] == (1, "BUY", 0.54, 3.0)
    assert f.mid_at(0, now + 1) == 0.465 and f.mid_at(0, now - 1) is None


def test_latency_phase_measures_and_cancels():
    c = FakeClient(None)
    t = tester(c, latency_n=3)
    t.run_latency(3)
    lat = t.records["latency"]
    assert len(lat) == 3 and not t.stop_reason
    for r in lat:
        assert r["price"] <= 0.50 - 0.15 + 1e-9 and r["level_before"] == 0   # far below the bid, empty level
        assert r["cancel_ok"] and r["visible_after_send_ms"] is not None and r["gone_after_send_ms"] is not None
        assert 20 <= r["visible_after_send_ms"] < 500 and 10 <= r["gone_after_send_ms"] < 500
    assert not t.open_ids and t.budget.spent == 0
    s = t.summary()
    assert s["latency"]["visible_after_send_ms"]["n"] == 3
    assert s["measured_for_paper"]["latency_s"] is not None and s["measured_for_paper"]["cancel_latency_s"] is not None


def test_maker_phase_real_vs_paper():
    c = FakeClient(None, fill_maker=5.0)
    t = tester(c, maker_n=2, hold=2.0)
    t.run_maker(2, 2.0)
    mk = t.records["maker"]
    assert len(mk) == 2
    for r in mk:
        assert r["real_filled"] == 5.0 and r["queue_ahead"] == 100 and r["price"] == 0.50
        assert r["paper_front_filled"] == 5.0 and math.isclose(r["paper_queue_filled"], 5.0)   # 200 sold > 100 ahead
    assert math.isclose(t.budget.spent, 2 * 5 * 0.50)
    t.markouts()
    s = t.summary()
    assert s["maker"]["real_fill_rate"] == 1.0 and s["maker"]["paper_queue_fill_rate"] == 1.0
    # nobody trades -> no fill, order cancelled, paper models agree
    c2 = FakeClient(None)
    t2 = tester(c2, maker_n=1, hold=1.0)
    t2.run_maker(1, 1.0)
    r = t2.records["maker"][0]
    assert r["real_filled"] == 0 and r["paper_front_filled"] == 0 and not t2.open_ids


def test_taker_phase_and_budget_stop():
    c = FakeClient(None, taker_fill=0.5)
    t = tester(c, taker_n=2, taker_usd=1.0)
    t.run_taker(2, 1.0)
    tk = t.records["taker"]
    assert len(tk) == 2 and all(math.isclose(r["fill_ratio"], 0.5) for r in tk)
    assert all(r["ask"] == 0.52 and r["avg_price"] <= 0.52 + 1e-9 for r in tk)
    assert all("exchange_match_after_decision_ms" in r for r in tk)
    # tiny budget: stops before sending anything it cannot afford
    c2 = FakeClient(None)
    t2 = tester(c2, budget=0.5)
    t2.run_taker(3, 1.0)
    assert t2.stop_reason == "budget" and c2.n == 0


def test_fatal_rejection_stops_and_cancel_all():
    c = FakeClient(None, reject="not_enough_balance")
    t = tester(c)
    t.run_latency(5)
    assert t.stop_reason == "latency: not_enough_balance" and c.n == 1
    t.cancel_all()
    assert c.cancel_all_calls == 1
    c2 = FakeClient(None, reject="post_only_would_cross")   # non-fatal: keeps going, records errors
    t2 = tester(c2)
    t2.run_latency(3)
    assert t2.stop_reason is None and len(t2.records["errors"]) == 3


def test_live_mode_refuses_without_preconditions():
    orig_geo, orig_env = olt.geoblock, {k: os.environ.pop(k, None) for k in
                                        ("POLYMARKET_PRIVATE_KEY", "POLYMARKET_WALLET_ADDRESS",
                                         "POLY_PRIVATE_KEY", "POLY_FUNDER_ADDRESS")}
    orig_dotenv = olt.load_dotenv
    try:
        olt.load_dotenv = lambda _p: None
        for geo, flag, msg in (({"blocked": True, "country": "US"}, True, "geoblock"),
                               ({"blocked": None, "error": "x"}, True, "geoblock"),
                               ({"blocked": False, "country": "TR"}, False, "--i-accept-real-money"),
                               ({"blocked": False, "country": "TR"}, True, "POLYMARKET_PRIVATE_KEY")):
            olt.geoblock = lambda _s, g=geo: g
            try:
                olt.run_live(args(i_accept_real_money=flag), log=lambda *_a: None)
                raise AssertionError("run_live should have stopped")
            except SystemExit as exc:
                assert msg in str(exc), exc
    finally:
        olt.geoblock, olt.load_dotenv = orig_geo, orig_dotenv
        for k, v in orig_env.items():
            if v is not None:
                os.environ[k] = v


def test_measured_variants_and_report():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "variants").mkdir()
    shutil.copy(ROOT / "variants" / "v3.json", tmp / "variants" / "v3.json")
    orig = olt.ROOT
    try:
        olt.ROOT = tmp
        p = olt.write_measured_variants({"latency_s": 0.42, "cancel_latency_s": 0.31}, "t")
        v = {x["name"]: x for x in json.loads(p.read_text())}
        assert v["v3_mm_fast"]["latency"] == 0.42 and v["v3_mm_fast"]["cancel_latency"] == 0.31
        assert "latency" not in v["base"]
        assert olt.write_measured_variants({"latency_s": None}, "t2") is None
    finally:
        olt.ROOT = orig
        shutil.rmtree(tmp)
    c = FakeClient(None, fill_maker=5.0)
    t = tester(c)
    t.run_latency(2)
    t.run_maker(1, 1.0)
    t.run_taker(1, 1.0)
    out = {"mode": "live", "started": "s", "finished": "f", "geoblock": {"country": "TR", "region": "34", "blocked": False},
           "clock": {"source": "x", "offset_ms": 0}, "summary": t.summary()}
    md = olt.report_md(out)
    assert "Paper varsayımlarıyla karşılaştırma" in md and "gerçek" in md
    probe = {"mode": "probe", "started": "s", "finished": "f", "geoblock": {"blocked": True}, "clock": {},
             "rest_rtt_ms": {"GET /time": olt.stats([10, 12])}, "sign_ms": olt.stats([3, 4]),
             "ws_lag_ms": {"polymarket_market_channel": olt.stats([50]), "binance_futures_bookTicker": olt.stats([])},
             "rest_cold_connect_ms": 100, "sign_first_ms": 300, "estimate_decision_to_exchange_ms": 60}
    assert "emir gönderilmedi" in olt.report_md(probe)


def test_bot_live_executor_prefers_v2_sdk():
    """bot.LiveExecutor must sign through polymarket-client (CLOB V2) when it is installed (fake module here)."""
    import types
    import bot
    calls = []

    class FakeSC:
        @classmethod
        def create(cls, private_key, wallet=None):
            calls.append(("create", private_key, wallet))
            return cls()

        def create_market_order(self, **kw):
            calls.append(("sign", kw))
            return kw

        def post_order(self, signed):
            if signed["side"] == "SELL":
                return SimpleNamespace(ok=False, code="fak_not_filled", message="no liquidity")
            return SimpleNamespace(ok=True, order_id="o1", status="matched", making_amount=1, taking_amount=2)

    mod = types.ModuleType("polymarket")
    mod.SecureClient = FakeSC
    orig_mod = sys.modules.get("polymarket")
    sys.modules["polymarket"] = mod
    os.environ["OLT_TEST_PK"], os.environ["OLT_TEST_FUNDER"] = "0xkey", "0xwallet"
    try:
        cfg = {"api": {"clob_api": "x"}, "live_trading": {"env_vars": {
            "private_key": "OLT_TEST_PK", "funder": "OLT_TEST_FUNDER", "api_key": "A", "api_secret": "B",
            "api_passphrase": "C"}}}
        ex = bot.LiveExecutor(cfg)
        assert ex.backend == "polymarket-client" and calls[0] == ("create", "0xkey", "0xwallet")
        r = ex.market_order("TOK", "BUY", 2.349)
        assert r["success"] and r["order_id"] == "o1"
        assert calls[-1][1] == {"asset_id": "TOK", "side": "BUY", "amount": "2.34", "order_type": "FOK"}
        r = ex.market_order("TOK", "SELL", 7.999)
        assert not r["success"] and r["code"] == "fak_not_filled"
        assert calls[-1][1]["shares"] == "7.99"          # floored: never sell more than held
    finally:
        del os.environ["OLT_TEST_PK"], os.environ["OLT_TEST_FUNDER"]
        if orig_mod is not None:
            sys.modules["polymarket"] = orig_mod
        else:
            sys.modules.pop("polymarket", None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
