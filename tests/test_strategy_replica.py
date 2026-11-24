"""Offline tests for the strategy replica (no network).
Run:  python -m pytest -q tests   (or: python tests/test_strategy_replica.py)"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import load_config  # noqa: E402
from fair_value import LiveFairValue, ewma_variance, fair_up_series  # noqa: E402
from live_paper import LiveStrategyPaperBot, PaperMarket  # noqa: E402
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


def test_live_paper_taker_consumption_mirrored():
    cfg = load_config()
    assert cfg["live_trading"]["enabled"] is False                 # live trading stays locked by default
    bot = LiveStrategyPaperBot(cfg, P, tag="unittest")
    bot.fills_path = Path("/home/ubuntu/.tmp/unittest_fills.csv")
    m = PaperMarket({"slug": "btc-updown-5m-0", "tokens": ["a", "b"], "fee_rate": 0.0, "window_start": 0,
                     "window_end": 300}, PairStrategy(P, 0.0, 0.01, 5, 400))
    m.books[1]["asks"] = {0.33: 30.0}                              # Down ask 0.33 (== Up bid 0.67)
    m.books[0]["bids"] = {0.67: 30.0}
    m.inv.apply_buy(0, 0.6, 50, 0.0, True)
    bot._exec_taker(m, {"side": "SELL", "i": 0, "limit": 0.67, "size": 25}, 1.0)
    bot._exec_taker(m, {"side": "BUY", "i": 1, "limit": 0.33, "size": 25}, 1.0)
    assert math.isclose(m.inv.shares[0], 25) and math.isclose(m.inv.shares[1], 5)   # only 30 sh existed


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
