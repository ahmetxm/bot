"""Offline tests (no network): copy logic, risk limits, live-mode guard and a full paper-bot cycle
against a fake API.   Run:  python -m pytest -q tests   (or: python tests/test_copy_bot.py)"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import CopyEngine, CopyTradeBot, LiveTradingDisabled  # noqa: E402
from common import load_config  # noqa: E402
from paper_trader import PaperTrader  # noqa: E402

RISK = {"max_position_pct": 0.10, "max_daily_loss": 500, "stop_loss_pct": 0.05, "stop_loss_action": "warn",
        "min_order_shares": 5, "min_order_usd": 1}
FEES = {"btc_updown_short_rate": 0.05, "crypto_other_rate": 0.01}


def tmp_cfg() -> dict:
    cfg = load_config()
    root = Path(tempfile.mkdtemp(prefix="polybot_test_"))
    for k in ("data_dir", "reports_dir", "logs_dir"):
        if k in cfg["paths"]:
            (root / k).mkdir(parents=True, exist_ok=True)
            cfg["paths"][k] = str(root / k)
    cfg["bot"]["state_file"] = "data_dir/bot_state.json"
    cfg["sizing"]["target_capital_usd"] = 50000          # -> copy ratio 10_000 / 50_000 = 0.2
    return cfg


def test_canonical_sell_becomes_opposite_buy():
    eng = CopyEngine(target_capital=1.0, fixed_ratio=1.0)
    out = eng.process("m", [(1, "SELL", 100.0, 0.30)], 0.0)   # sells outcome 1 it never bought
    assert len(out) == 1 and out[0].side == "BUY" and out[0].outcome_index == 0
    assert abs(out[0].amount - 100.0) < 1e-9 and abs(out[0].ref_price - 0.70) < 1e-9
    out = eng.process("m", [(0, "SELL", 40.0, 0.75)], 0.0)    # then reduces it
    assert out[0].side == "SELL" and abs(out[0].amount - 0.4) < 1e-9


def test_risk_limits():
    tr = PaperTrader(10_000, RISK, FEES, name="t")
    meta = {"category": "BTC 5m", "title": "x"}
    got = tr.buy(0, "a", 0, 10_000, 0.5, meta)                 # wants $5,000 -> clipped to 10% of equity
    assert abs(got - 2000) < 1e-6 and tr.rejections["clipped_max_position"] == 1
    assert abs(tr.fees_paid - 2000 * 0.05 * 0.5 * 0.5) < 1e-9   # taker fee = shares * rate * p * (1-p)
    assert tr.buy(1, "a", 0, 100, 0.5, meta) == 0.0            # market already at the cap
    tr.mark(2, "a", 0, 0.01)                                   # -> stop-loss warning (> 5% of equity)
    assert any(w["type"] == "STOP_LOSS" for w in tr.warnings)
    tr.resolve(3, "a", [0, 1])                                 # loses ~ $1,000 -> daily-loss halt
    assert tr.is_halted(3) and tr.buy(4, "b", 0, 10, 0.5, meta) == 0.0
    assert tr.rejections["daily_loss_halt"] == 1


def test_live_mode_refused_by_default():
    cfg = tmp_cfg()
    assert cfg["live_trading"]["enabled"] is False
    try:
        CopyTradeBot(cfg, mode="live", api=FakeAPI())
    except LiveTradingDisabled:
        return
    raise AssertionError("live mode must be refused while live_trading.enabled is false")


class FakeAPI:
    """Serves 3 historical fills, then 3 fresh fills in a live BTC 5m market, then resolves it (Up wins)."""

    def __init__(self):
        now = int(time.time())
        self.cid = "0xabc"
        slug = f"btc-updown-5m-{now // 300 * 300}"
        base = {"condition_id": self.cid, "slug": slug, "title": "Bitcoin Up or Down - test"}
        self.history = [dict(base, transaction_hash=f"h{i}", token_id="T0", outcome_index=0, side="BUY",
                             size=10, price=0.5, timestamp=now - 600 - i) for i in range(3)]
        self.fresh = [dict(base, transaction_hash="n1", token_id="T0", outcome_index=0, side="BUY", size=1000,
                           price=0.40, timestamp=now),
                      dict(base, transaction_hash="n2", token_id="T1", outcome_index=1, side="BUY", size=800,
                           price=0.55, timestamp=now),
                      dict(base, transaction_hash="n3", token_id="T0", outcome_index=0, side="SELL", size=300,
                           price=0.45, timestamp=now)]
        self.calls = 0
        self.resolved = False

    def get_trades_page(self, user, limit=200, cursor=None, taker_only=False, **_):
        self.calls += 1
        # poll 1: history only | poll 2: two BUYs | poll 3+: plus a partial SELL
        rows = self.history + (self.fresh[:2] if self.calls == 2 else self.fresh if self.calls > 2 else [])
        return {"data": sorted(rows, key=lambda r: -r["timestamp"]), "pagination": {}}

    def get_tokens(self, condition_ids=None, **_):
        return [{"outcome_index": 0, "token_id": "T0"}, {"outcome_index": 1, "token_id": "T1"}]

    def get_midpoint(self, token_id):
        return 0.42 if token_id == "T0" else 0.58

    def get_resolutions(self, cids):
        return [{"condition_id": c, "status": "resolved", "payouts": [1, 0]} for c in cids] if self.resolved else []


def test_paper_bot_cycle():
    cfg = tmp_cfg()
    cfg["bot"]["resolution_check_seconds"] = 0
    cfg["bot"]["mark_to_market_seconds"] = 0
    api = FakeAPI()
    bot = CopyTradeBot(cfg, mode="paper", api=api)
    bot.run(max_iterations=1, sleep_fn=lambda s: None)           # init: history marked as seen
    assert bot.trader.trade_log == []
    bot.run(max_iterations=1, sleep_fn=lambda s: None)           # copies 2 BUYs (ratio 0.2)
    assert [t["side"] for t in bot.trader.trade_log] == ["BUY", "BUY"]
    assert abs(bot.trader.holding(api.cid, 0) - 200) < 1e-6 and abs(bot.trader.holding(api.cid, 1) - 160) < 1e-6
    bot.run(max_iterations=1, sleep_fn=lambda s: None)           # target sells 30% of outcome 0 -> we do too
    assert [t["side"] for t in bot.trader.trade_log] == ["BUY", "BUY", "SELL"]
    assert abs(bot.trader.holding(api.cid, 0) - 140) < 1e-6
    assert len(bot.trader.positions) == 2
    api.resolved = True
    s = bot.run(max_iterations=1, sleep_fn=lambda s: None)       # resolution -> PnL booked
    assert not bot.trader.positions and s["n_resolved_markets"] == 1
    assert abs(s["final_equity"] - bot.trader.cash) < 0.01   # metrics are rounded to cents
    st = Path(cfg["paths"]["data_dir"]) / "bot_state.json"
    assert st.exists()
    print(f"paper cycle OK: orders={s['n_orders']} PnL={s['total_pnl']:.2f} fees={s['fees_paid']:.2f}")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
