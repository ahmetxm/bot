"""Offline tests for the strategy replica (no network).
Run:  python -m pytest -q tests   (or: python tests/test_strategy_replica.py)"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import load_config  # noqa: E402
from fair_value import LiveFairValue, ewma_variance, fair_up_series  # noqa: E402
from live_paper import LiveStrategyPaperBot, PaperMarket, VariantMarket, build_variants  # noqa: E402
from pair_strategy import Inventory, PairStrategy, StrategyParams, taker_fee_per_share  # noqa: E402
from strategy_backtest import simulate_market  # noqa: E402

P = StrategyParams(markets=["BTC 5m"], half_spread=0.03, inventory_skew=0.0, max_imbalance_shares=50,
                   order_shares=20, guard_move=0.0, take_edge=0.04, take_shares=20)
BT = {"latency_seconds": 1, "queue_fill_fraction": 0.0, "taker_share_of_print": 1.0,
      "tape_timestamp_lag_seconds": 0, "maker_rebate_rate": 0.0}


def test_inventory_and_fees():
    inv = Inventory()
    inv.apply_buy(0, 0.40, 10, 0.1, True)
    inv.apply_buy(1, 0.50, 10, 0.0, True)
    assert math.isclose(inv.cost_basis, 9.1)
    assert math.isclose(inv.avg_cost(0) + inv.avg_cost(1), 0.90)
    assert inv.apply_sell(0, 0.6, 50, 0.0, False) == 10          # cannot sell more than held
    assert math.isclose(inv.settle([0.0, 1.0]), 10 * 1.0 - (4.0 - 6.0) - 5.0 - 0.1)   # = 6.9
    assert math.isclose(taker_fee_per_share(0.5, 0.05), 0.0125)


def test_quotes_tick_postonly_and_limits():
    s = PairStrategy(P, fee_rate=0.05, tick=0.001)                 # resolution-time tick 0.001 -> 0.01
    q = s.quotes(100, 0, 300, 0.555, Inventory(), [None, None], [None, None])
    assert set(q) == {0, 1}
    for i, (px, _) in q.items():
        assert abs(px * 100 - round(px * 100)) < 1e-9, px         # whole cents
    assert math.isclose(q[0][0], 0.52) and math.isclose(q[1][0], 0.41)
    q = s.quotes(100, 0, 300, 0.60, Inventory(), [None, None], [0.55, None])
    assert q[0][0] < 0.55                                          # post-only: never at/through the ask
    heavy = Inventory()
    heavy.apply_buy(0, 0.5, 60, 0.0, True)
    q = s.quotes(100, 0, 300, 0.5, heavy, [None, None], [None, None])
    assert 0 not in q and 1 in q                                   # imbalance limit stops the heavy side
    assert q[1][0] <= P.pair_cost_cap - 0.5 + 1e-9                 # completing the pair stays below the cap
    assert s.quotes(299, 0, 300, 0.5, Inventory(), [None, None], [None, None]) == {}   # stop before end
    g = PairStrategy(StrategyParams(**{**P.as_dict(), "guard_move": 0.02}), 0.05)
    q = g.quotes(100, 0, 300, 0.50, Inventory(), [None, None], [None, None], fair_up_prev=0.55)
    assert 0 not in q and 1 in q                                   # Up fair collapsing -> pull the Up bid


def test_taker_orders_no_mirrored_duplicate():
    s = PairStrategy(P, fee_rate=0.01)
    inv = Inventory()
    inv.apply_buy(0, 0.5, 40, 0.0, True)
    # Up bid 0.80 >> fair 0.60 (sell Up) and Down ask 0.20 << fair 0.40 (buy Down): same bet, keep one
    orders = s.taker_orders(100, 0, 300, 0.60, inv, [0.80, 0.18], [0.82, 0.20])
    assert [(o[0], o[1]) for o in orders] == [("SELL", 0)]


def test_fair_value_properties():
    n = 4000
    logs = np.log(np.full(n, 100.0))
    ev = ewma_variance(logs + np.cumsum(np.r_[0, np.tile([1e-4, -1e-4], (n - 1) // 2 + 1)[: n - 1]]), 600)
    f = fair_up_series(logs, ev, 0, 3600, 3900, 3700, 3700, 60, 1.0, 0.35e-4)
    assert abs(f[0] - 0.5) < 1e-6                                  # flat price at the strike -> 50/50
    up = logs.copy(); up[3650:] += 5e-4
    fu = fair_up_series(up, ev, 0, 3600, 3900, 3660, 3899, 60, 1.0, 0.35e-4)
    assert fu[0] > 0.5 and fu[-1] > 0.99 and np.all(np.diff(fu) >= -1e-9)   # certainty grows to the end
    lf = LiveFairValue(600, 1.0, 0.35e-4)
    lf.seed(0, np.exp(up[:3800]))
    assert math.isclose(lf.p_up(3799, 3600, 3900, 60), float(fair_up_series(
        up[:3800], ewma_variance(up[:3800], 600), 0, 3600, 3900, 3799, 3799, 60, 1.0, 0.35e-4)[0]), rel_tol=1e-9)
    shifted = lf.p_up(3799, 3600, 3900, 60, shift=lambda t0, k: np.full(k, 0.001))
    assert math.isclose(shifted, lf.p_up(3799, 3600, 3900, 60), rel_tol=1e-9)   # constant basis cancels


def test_simulator_fill_rules_and_settlement():
    meta = {"slug": "btc-updown-5m-0", "category": "BTC 5m", "window_start": 0, "window_end": 300,
            "fee_rate": 0.05, "tick": 0.01, "min_size": 5, "payouts": [1.0, 0.0]}
    fair = np.full(301, 0.5)                                      # quotes: Up 0.47, Down 0.47
    tape = [[50, "SELL", 0, 0.47, 100.0],                          # at our price -> no fill (queue fraction 0)
            [60, "SELL", 0, 0.45, 100.0],                          # through our Up bid -> 20 sh
            [70, "BUY", 0, 0.55, 100.0]]                           # Up bought at 0.55 == Down sold at 0.45 -> 20 sh
    r = simulate_market(meta, tape, fair, StrategyParams(**{**P.as_dict(), "take_enabled": False}), BT, 400)
    assert r["maker_fills"] == 2 and r["shares"] == [20.0, 20.0]
    assert math.isclose(r["pnl"], 20 * 1.0 - 20 * 0.47 - 20 * 0.47)
    assert r["two_sided"] and math.isclose(r["pair_cost"], 0.94)


TMP = Path(tempfile.gettempdir()) / "polymarket_bot_tests"      # honours TMPDIR (works on CI runners too)
TMP.mkdir(parents=True, exist_ok=True)
META = {"slug": "btc-updown-5m-0", "tokens": ["a", "b"], "fee_rate": 0.0, "window_start": 0, "window_end": 300,
        "category": "BTC 5m"}


def test_live_paper_taker_consumption_mirrored():
    cfg = load_config()
    assert cfg["live_trading"]["enabled"] is False                 # live trading stays locked by default
    bot = LiveStrategyPaperBot(cfg, P, tag="unittest")
    v = bot.variants[0]
    v.fills_path = TMP / "unittest_fills.csv"
    m = PaperMarket(dict(META))
    m.vm[v.name] = VariantMarket(PairStrategy(P, 0.0, 0.01, 5, 400))
    vm = m.vm[v.name]
    m.books[1]["asks"] = {0.33: 30.0}                              # Down ask 0.33 (== Up bid 0.67)
    m.books[0]["bids"] = {0.67: 30.0}
    vm.inv.apply_buy(0, 0.6, 50, 0.0, True)
    bot._exec_taker(m, v, {"side": "SELL", "i": 0, "limit": 0.67, "size": 25}, 1.0)
    bot._exec_taker(m, v, {"side": "BUY", "i": 1, "limit": 0.33, "size": 25}, 1.0)
    assert math.isclose(vm.inv.shares[0], 25) and math.isclose(vm.inv.shares[1], 5)   # only 30 sh existed


def test_live_paper_variants_are_independent():
    cfg = load_config()
    spec = [{"name": "a", "set": {"half_spread": 0.03}},
            {"name": "b", "set": {"half_spread": 1.0, "vol_multiplier": 2.0}, "latency": 0.3, "interval": 0.25}]
    variants = build_variants(cfg, P, spec)
    bot = LiveStrategyPaperBot(cfg, variants, tag="unittest_multi")
    a, b = bot.variants
    assert b.p.vol_multiplier == a.p.vol_multiplier                # shared fair value -> shared vol model
    assert b.latency == 0.3 and b.interval == 0.25 and a.latency == float(cfg["strategy_backtest"]["latency_seconds"])
    for v in bot.variants:
        v.fills_path = TMP / f"unittest_fills_{v.name}.csv"
    m = PaperMarket(dict(META))
    for v in bot.variants:
        m.vm[v.name] = VariantMarket(PairStrategy(v.p, 0.0, 0.01, 5, 400))
    m.vm["a"].quotes[0] = {"price": 0.47, "rem": 20.0, "live_from": 0.0, "ahead": 0.0}
    bot._on_print(m, 0, "SELL", 0.45, 100.0, 10.0)                  # through a's Up bid
    assert math.isclose(m.vm["a"].inv.shares[0], 20) and m.vm["b"].inv.shares == [0.0, 0.0]
    # one taker per variant may use the same real liquidity (separate hypothetical accounts)
    m.books[0]["asks"] = {0.40: 25.0}
    for v in bot.variants:
        bot._exec_taker(m, v, {"side": "BUY", "i": 0, "limit": 0.40, "size": 25}, 11.0)
    assert math.isclose(m.vm["b"].inv.shares[0], 25) and math.isclose(m.vm["a"].inv.shares[0], 45)


def test_cutoff_fractions():
    s = PairStrategy(StrategyParams(**{**P.as_dict(), "take_cutoff_frac": 0.5, "maker_cutoff_frac": 0.25}), 0.0)
    assert s.taker_orders(100, 0, 300, 0.70, Inventory(), [None, None], [0.50, None])   # 1/3 of window: active
    assert s.taker_orders(200, 0, 300, 0.70, Inventory(), [None, None], [0.50, None]) == []
    assert s.quotes(60, 0, 300, 0.5, Inventory(), [None, None], [None, None])
    assert s.quotes(100, 0, 300, 0.5, Inventory(), [None, None], [None, None]) == {}


def test_fast_fair_value_now_logs():
    n = 4000
    rng = np.random.default_rng(1)
    logs = np.log(100.0) + np.cumsum(rng.normal(0, 1e-4, n))
    lf = LiveFairValue(600, 1.0, 0.35e-4)
    lf.seed(0, np.exp(logs[:3800]))
    base = lf.p_up(3799, 3600, 3900, 60)
    same, up, down = lf.p_up(3799, 3600, 3900, 60, now_logs=(logs[3799], logs[3799] + 5e-4, logs[3799] - 5e-4))
    assert math.isclose(same, base, rel_tol=1e-9)                  # unchanged price -> unchanged fair value
    assert up > base > down                                        # higher fast price -> higher P(Up)
    later = lf.p_up(3802, 3600, 3900, 60, now_logs=(logs[3799],))  # no spot print yet: series carried forward
    assert 0.0 < later[0] < 1.0


def test_fade_cancel_and_cancel_latency():
    cfg = load_config()
    spec = [{"name": "plain"}, {"name": "fade", "fade": 0.01, "cancel_latency": 0.2, "latency": 0.3}]
    bot = LiveStrategyPaperBot(cfg, build_variants(cfg, P, spec), tag="unittest_fade")
    plain, fade = bot.variants
    assert fade.fast and not plain.fast and fade.cancel_latency == 0.2 and bot.fast is not None
    for v in bot.variants:
        v.fills_path = TMP / f"unittest_fills_fade_{v.name}.csv"
    m = PaperMarket(dict(META, asset="BTC"))
    for v in bot.variants:
        m.vm[v.name] = VariantMarket(PairStrategy(v.p, 0.0, 0.01, 5, 400))
    bot.markets[m.meta["slug"]] = m
    q = {"price": 0.47, "rem": 20.0, "live_from": 0.0, "ahead": 0.0}
    m.vm["plain"].quotes[0] = dict(q)
    m.vm["fade"].quotes[0] = dict(q, fair_ref=0.50, dfair=40.0, log_ref=0.0)    # dP(Up)/dlog = 40
    bot._on_fast_move("BTC", -1e-4, 100.0)                         # fair -0.004 < 0.01: keep the quote
    assert 0 in m.vm["fade"].quotes and fade.n_fades == 0
    bot._on_fast_move("BTC", -3e-4, 100.0)                         # fair -0.012 >= 0.01: cancel (lands at 100.2)
    assert 0 not in m.vm["fade"].quotes and fade.n_fades == 1 and m.vm["fade"].dying[0]["dead_from"] == 100.2
    bot._on_print(m, 0, "SELL", 0.45, 5.0, 100.1)                  # before the cancel lands -> still filled
    assert math.isclose(m.vm["fade"].inv.shares[0], 5) and fade.n_late == 1
    bot._on_print(m, 0, "SELL", 0.45, 100.0, 100.3)                # after: only the plain variant is filled
    assert math.isclose(m.vm["fade"].inv.shares[0], 5) and math.isclose(m.vm["plain"].inv.shares[0], 20)
    # a replaced quote stays live for cancel_latency (no instant cancels in the paper model)
    vm = m.vm["plain"]
    vm.quotes[1] = {"price": 0.40, "rem": 20.0, "live_from": 0.0, "ahead": 0.0}
    bot._retire(vm, 1, 101.0)
    bot._on_print(m, 1, "SELL", 0.39, 10.0, 100.5)
    assert math.isclose(vm.inv.shares[1], 10) and plain.n_late == 1
    # an old (being cancelled) and a new quote at the same price share one print's volume
    vm.quotes[1] = {"price": 0.40, "rem": 20.0, "live_from": 0.0, "ahead": 0.0}
    bot._on_print(m, 1, "SELL", 0.39, 12.0, 100.6)
    assert math.isclose(vm.inv.shares[1], 22)
    bot.markets.clear()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
