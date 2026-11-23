"""Paper-trading engine: virtual portfolio, risk limits, PnL accounting and performance metrics.

Risk controls (all configurable in config.yaml -> risk):
  * max_position_pct  - exposure per market capped at X% of current equity (orders are clipped)
  * max_daily_loss    - once realized PnL of the UTC day <= -limit, new entries are halted until next day
  * stop_loss_pct     - an open position losing more than X% of equity triggers a WARNING
                        (and is closed at market if stop_loss_action == "close"); a resolved market
                        losing more than X% of equity is also flagged
  * min_order_*       - Polymarket minimum order size / notional
"""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from common import payout_per_share, save_json, taker_fee, utc

EPS = 1e-9


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Position:
    condition_id: str
    outcome_index: int
    shares: float = 0.0
    cost: float = 0.0            # remaining cost basis (incl. fees)
    opened_ts: float = 0.0
    category: str = ""
    title: str = ""
    last_price: Optional[float] = None
    sl_warned: bool = False

    @property
    def avg_price(self) -> float:
        return self.cost / self.shares if self.shares > EPS else 0.0

    def value(self) -> float:
        px = self.last_price if self.last_price is not None else self.avg_price
        return self.shares * px


@dataclass
class PaperTrader:
    starting_balance: float
    risk: dict
    fees: dict
    name: str = "paper"
    enforce_limits: bool = True
    apply_fees: bool = True
    logger: Optional[logging.Logger] = None
    log_each_trade: bool = False

    cash: float = field(init=False)
    positions: dict = field(init=False, default_factory=dict)
    market_cost: dict = field(init=False, default_factory=lambda: defaultdict(float))
    market_deployed: dict = field(init=False, default_factory=lambda: defaultdict(float))
    market_pnl: dict = field(init=False, default_factory=lambda: defaultdict(float))
    market_meta: dict = field(init=False, default_factory=dict)
    daily_realized: dict = field(init=False, default_factory=lambda: defaultdict(float))
    halted_days: set = field(init=False, default_factory=set)
    trade_log: list = field(init=False, default_factory=list)
    closed_markets: list = field(init=False, default_factory=list)
    equity_curve: list = field(init=False, default_factory=list)
    rejections: Counter = field(init=False, default_factory=Counter)
    warnings: list = field(init=False, default_factory=list)
    fees_paid: float = field(init=False, default=0.0)
    volume: float = field(init=False, default=0.0)
    min_cash: float = field(init=False, default=0.0)
    peak_open_cost: float = field(init=False, default=0.0)
    open_cost: float = field(init=False, default=0.0)

    def __post_init__(self):
        self.cash = float(self.starting_balance)
        self.min_cash = self.cash
        self.log = self.logger or logging.getLogger(f"paper.{self.name}")

    # ------------------------------------------------------------ helpers
    def equity(self) -> float:
        return self.cash + sum(p.value() for p in self.positions.values())

    def holding(self, cid: str, idx: int) -> float:
        p = self.positions.get((cid, idx))
        return p.shares if p else 0.0

    def is_halted(self, ts: float) -> bool:
        return _day(ts) in self.halted_days

    def _warn(self, ts: float, kind: str, msg: str) -> None:
        self.warnings.append({"ts": ts, "time": utc(ts), "type": kind, "message": msg})
        self.log.warning("[%s] %s | %s", self.name, kind, msg)

    def _record(self, ts, cid, idx, side, shares, price, fee, reason, realized=0.0):
        notional = shares * price
        self.volume += notional
        self.fees_paid += fee
        meta = self.market_meta.get(cid, {})
        rec = {"ts": ts, "time": utc(ts), "condition_id": cid, "outcome_index": idx, "side": side,
               "shares": round(shares, 6), "price": round(price, 6), "notional": round(notional, 6),
               "fee": round(fee, 6), "realized_pnl": round(realized, 6), "reason": reason,
               "cash_after": round(self.cash, 4), "category": meta.get("category", ""),
               "title": meta.get("title", "")}
        self.trade_log.append(rec)
        if self.log_each_trade:
            self.log.info("[%s] %s %.2f sh @ %.4f (%s) %s | fee %.4f | cash %.2f",
                          self.name, side, shares, price, reason, meta.get("title", cid[:10]), fee, self.cash)

    def _book_realized(self, ts: float, cid: str, pnl: float) -> None:
        day = _day(ts)
        self.daily_realized[day] += pnl
        self.market_pnl[cid] += pnl
        limit = float(self.risk.get("max_daily_loss", math.inf))
        if self.enforce_limits and day not in self.halted_days and self.daily_realized[day] <= -limit:
            self.halted_days.add(day)
            self._warn(ts, "DAILY_LOSS_HALT",
                       f"realized PnL today {self.daily_realized[day]:.2f} <= -{limit:.2f}: new entries halted until next UTC day")

    def _sync_open_cost(self, delta: float) -> None:
        self.open_cost += delta
        if self.open_cost > self.peak_open_cost:
            self.peak_open_cost = self.open_cost

    # ------------------------------------------------------------- orders
    def size_buy(self, ts: float, cid: str, shares: float, price: float, count: bool = True) -> float:
        """Apply risk limits to a desired BUY; returns the allowed share amount (0 = rejected).
        Used directly by the live executor to size real orders before sending them."""
        if shares <= EPS:
            return 0.0
        if not self.enforce_limits:
            return shares
        rej = self.rejections if count else Counter()
        if self.is_halted(ts):
            rej["daily_loss_halt"] += 1
            return 0.0
        cat = self.market_meta.get(cid, {}).get("category", "")
        room = float(self.risk.get("max_position_pct", 1.0)) * self.equity() - self.market_cost.get(cid, 0.0)
        if room <= EPS:
            rej["max_position"] += 1
            return 0.0
        if shares * price > room:
            shares = room / price
            rej["clipped_max_position"] += 1
        unit_fee = taker_fee(1.0, price, cat, self.fees) if self.apply_fees else 0.0
        if shares * (price + unit_fee) > self.cash:
            shares = max(self.cash, 0.0) / (price + unit_fee)
            rej["clipped_cash"] += 1
        if shares < float(self.risk.get("min_order_shares", 0)) or \
                shares * price < float(self.risk.get("min_order_usd", 0)):
            rej["below_min_order"] += 1
            return 0.0
        return shares

    def buy(self, ts: float, cid: str, idx: int, shares: float, price: float, meta: Optional[dict] = None,
            reason: str = "copy") -> float:
        """Open/increase a position. Returns executed shares (0 if rejected)."""
        if meta:
            self.market_meta.setdefault(cid, meta)
        price = min(max(float(price), 0.001), 0.999)
        shares = self.size_buy(ts, cid, shares, price)
        if shares <= EPS:
            return 0.0
        cat = self.market_meta.get(cid, {}).get("category", "")
        fee = taker_fee(shares, price, cat, self.fees) if self.apply_fees else 0.0
        cost = shares * price + fee
        self.cash -= cost
        self.min_cash = min(self.min_cash, self.cash)
        key = (cid, idx)
        pos = self.positions.get(key)
        if pos is None:
            m = self.market_meta.get(cid, {})
            pos = Position(cid, idx, opened_ts=ts, category=cat, title=m.get("title", ""))
            self.positions[key] = pos
        pos.shares += shares
        pos.cost += cost
        pos.last_price = price
        self.market_cost[cid] += cost
        self.market_deployed[cid] += cost
        self._sync_open_cost(cost)
        self._record(ts, cid, idx, "BUY", shares, price, fee, reason)
        return shares

    def sell(self, ts: float, cid: str, idx: int, shares: float, price: float, reason: str = "copy") -> float:
        """Reduce/close a position (always allowed, even when halted). Returns executed shares."""
        key = (cid, idx)
        pos = self.positions.get(key)
        if pos is None or pos.shares <= EPS or shares <= EPS:
            return 0.0
        price = min(max(float(price), 0.001), 0.999)
        shares = min(shares, pos.shares)
        if self.enforce_limits and shares < float(self.risk.get("min_order_shares", 0)) - EPS:
            self.rejections["below_min_order_sell"] += 1
            return 0.0
        fee = taker_fee(shares, price, pos.category, self.fees) if self.apply_fees else 0.0
        proceeds = shares * price - fee
        basis = pos.avg_price * shares
        realized = proceeds - basis
        self.cash += proceeds
        pos.shares -= shares
        pos.cost -= basis
        pos.last_price = price
        self.market_cost[cid] -= basis
        self._sync_open_cost(-basis)
        if pos.shares <= 1e-7:
            del self.positions[key]
        self._record(ts, cid, idx, "SELL", shares, price, fee, reason, realized)
        self._book_realized(ts, cid, realized)
        return shares

    # -------------------------------------------------------- marking/SL
    def mark(self, ts: float, cid: str, idx: int, price: float) -> None:
        pos = self.positions.get((cid, idx))
        if pos is None:
            return
        pos.last_price = price
        if not self.enforce_limits or pos.sl_warned:
            return
        unreal = pos.shares * price - pos.cost
        threshold = float(self.risk.get("stop_loss_pct", 1.0)) * max(self.equity(), EPS)
        if unreal < -threshold:
            pos.sl_warned = True
            self._warn(ts, "STOP_LOSS", f"{pos.title or cid[:10]} outcome {idx}: unrealized {unreal:.2f} "
                                       f"exceeds {self.risk.get('stop_loss_pct'):.0%} of equity")
            if str(self.risk.get("stop_loss_action", "warn")).lower() == "close":
                self.sell(ts, cid, idx, pos.shares, price, reason="stop_loss")

    def resolve(self, ts: float, cid: str, payouts: list) -> Optional[float]:
        """Settle every open outcome of a resolved market. Returns market PnL (None if nothing held)."""
        touched = cid in self.market_deployed
        for idx in (0, 1, *range(2, len(payouts or []))):
            pos = self.positions.pop((cid, idx), None)
            if pos is None:
                continue
            pps = payout_per_share(payouts, idx)
            if pps is None:
                self.positions[(cid, idx)] = pos
                return None
            proceeds = pos.shares * pps
            realized = proceeds - pos.cost
            self.cash += proceeds
            self._sync_open_cost(-pos.cost)
            self._book_realized(ts, cid, realized)
        if not touched:
            return None
        self.market_cost.pop(cid, None)
        pnl = self.market_pnl.get(cid, 0.0)
        meta = self.market_meta.get(cid, {})
        deployed = self.market_deployed.get(cid, 0.0)
        self.closed_markets.append({"condition_id": cid, "title": meta.get("title", ""),
                                    "category": meta.get("category", ""), "resolved_ts": ts,
                                    "deployed": round(deployed, 6), "pnl": round(pnl, 6)})
        if self.enforce_limits:
            threshold = float(self.risk.get("stop_loss_pct", 1.0)) * max(self.equity() - pnl, EPS)
            if pnl < -threshold:
                self._warn(ts, "LARGE_LOSS", f"{meta.get('title', cid[:10])}: market loss {pnl:.2f} exceeded "
                                             f"{self.risk.get('stop_loss_pct'):.0%} of equity")
        return pnl

    def snapshot(self, ts: float) -> None:
        self.equity_curve.append((ts, self.equity(), self.cash, len(self.positions)))

    # ------------------------------------------------------------ metrics
    def metrics(self) -> dict:
        eq_now = self.equity()
        closed = pd.DataFrame(self.closed_markets)
        out = {"name": self.name, "starting_balance": self.starting_balance,
               "final_equity": round(eq_now, 2), "cash": round(self.cash, 2),
               "total_pnl": round(eq_now - self.starting_balance, 2),
               "return_pct": round((eq_now / self.starting_balance - 1) * 100, 3) if self.starting_balance else None,
               "n_orders": len(self.trade_log),
               "n_buys": sum(1 for t in self.trade_log if t["side"] == "BUY"),
               "n_sells": sum(1 for t in self.trade_log if t["side"] == "SELL"),
               "volume_usdc": round(self.volume, 2), "fees_paid": round(self.fees_paid, 2),
               "open_positions": len(self.positions),
               "open_positions_value": round(sum(p.value() for p in self.positions.values()), 2),
               "peak_open_cost": round(self.peak_open_cost, 2), "min_cash": round(self.min_cash, 2),
               "rejections": dict(self.rejections), "halted_days": sorted(self.halted_days),
               "n_warnings": len(self.warnings),
               "n_stop_loss_warnings": sum(1 for w in self.warnings if w["type"] == "STOP_LOSS"),
               "n_large_loss_warnings": sum(1 for w in self.warnings if w["type"] == "LARGE_LOSS")}
        if not closed.empty:
            wins = closed[closed.pnl > 0]
            losses = closed[closed.pnl < 0]
            gross_win, gross_loss = wins.pnl.sum(), -losses.pnl.sum()
            out.update({"n_resolved_markets": int(len(closed)),
                        "realized_pnl_resolved": round(closed.pnl.sum(), 2),
                        "win_rate_pct": round(len(wins) / len(closed) * 100, 2),
                        "avg_win": round(wins.pnl.mean(), 4) if len(wins) else 0.0,
                        "avg_loss": round(losses.pnl.mean(), 4) if len(losses) else 0.0,
                        "largest_win": round(closed.pnl.max(), 2), "largest_loss": round(closed.pnl.min(), 2),
                        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
                        "roi_on_deployed_pct": round(closed.pnl.sum() / closed.deployed.sum() * 100, 3)
                        if closed.deployed.sum() > 0 else None})
            by_cat = closed.groupby("category").agg(markets=("pnl", "size"), pnl=("pnl", "sum"),
                                                    win_rate=("pnl", lambda s: (s > 0).mean() * 100))
            out["by_category"] = {k: {kk: round(float(vv), 3) for kk, vv in v.items()}
                                  for k, v in by_cat.to_dict(orient="index").items()}
        out.update(self.risk_metrics())
        out["daily_realized_pnl"] = {k: round(v, 2) for k, v in sorted(self.daily_realized.items())}
        return out

    def equity_frame(self) -> pd.DataFrame:
        if not self.equity_curve:
            return pd.DataFrame(columns=["ts", "equity", "cash", "open_positions"])
        df = pd.DataFrame(self.equity_curve, columns=["ts", "equity", "cash", "open_positions"])
        df["time"] = pd.to_datetime(df.ts, unit="s", utc=True)
        return df

    def risk_metrics(self) -> dict:
        df = self.equity_frame()
        if len(df) < 3:
            return {"sharpe_hourly_annualized": None, "sharpe_daily_annualized": None,
                    "max_drawdown_usd": 0.0, "max_drawdown_pct": 0.0}
        eq = df.set_index("time")["equity"]
        peak = eq.cummax()
        dd = eq - peak
        res = {"max_drawdown_usd": round(float(-dd.min()), 2),
               "max_drawdown_pct": round(float(-(dd / peak).min() * 100), 3)}
        for label, rule, ann in (("hourly", "1h", 24 * 365), ("daily", "1D", 365)):
            r = eq.resample(rule).last().ffill().pct_change().dropna()
            if len(r) >= 2 and r.std() > 0:
                res[f"sharpe_{label}_annualized"] = round(float(r.mean() / r.std() * np.sqrt(ann)), 3)
            else:
                res[f"sharpe_{label}_annualized"] = None
            res[f"n_{label}_returns"] = int(len(r))
        return res

    # --------------------------------------------------------- persistence
    def save(self, out_dir: str | Path, prefix: str) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        m = self.metrics()
        save_json(m, out_dir / f"{prefix}_metrics.json")
        pd.DataFrame(self.trade_log).to_csv(out_dir / f"{prefix}_trades.csv.gz", index=False, compression="gzip")
        pd.DataFrame(self.closed_markets).to_csv(out_dir / f"{prefix}_markets.csv", index=False)
        self.equity_frame().to_csv(out_dir / f"{prefix}_equity.csv", index=False)
        if self.warnings:
            pd.DataFrame(self.warnings).to_csv(out_dir / f"{prefix}_warnings.csv", index=False)
        return m

    def to_state(self) -> dict:
        return {"cash": self.cash, "starting_balance": self.starting_balance,
                "positions": [asdict(p) for p in self.positions.values()],
                "market_cost": dict(self.market_cost), "market_deployed": dict(self.market_deployed),
                "market_pnl": dict(self.market_pnl), "market_meta": self.market_meta,
                "daily_realized": dict(self.daily_realized), "halted_days": sorted(self.halted_days),
                "closed_markets": self.closed_markets[-5000:], "trade_log": self.trade_log[-5000:],
                "equity_curve": self.equity_curve[-20000:], "warnings": self.warnings[-1000:],
                "fees_paid": self.fees_paid, "volume": self.volume, "rejections": dict(self.rejections),
                "open_cost": self.open_cost, "peak_open_cost": self.peak_open_cost}

    def load_state(self, st: dict) -> None:
        self.cash = float(st["cash"])
        self.positions = {(p["condition_id"], p["outcome_index"]): Position(**p) for p in st.get("positions", [])}
        self.market_cost = defaultdict(float, st.get("market_cost", {}))
        self.market_deployed = defaultdict(float, st.get("market_deployed", {}))
        self.market_pnl = defaultdict(float, st.get("market_pnl", {}))
        self.market_meta = st.get("market_meta", {})
        self.daily_realized = defaultdict(float, st.get("daily_realized", {}))
        self.halted_days = set(st.get("halted_days", []))
        self.closed_markets = st.get("closed_markets", [])
        self.trade_log = st.get("trade_log", [])
        self.equity_curve = [tuple(x) for x in st.get("equity_curve", [])]
        self.warnings = st.get("warnings", [])
        self.fees_paid = st.get("fees_paid", 0.0)
        self.volume = st.get("volume", 0.0)
        self.rejections = Counter(st.get("rejections", {}))
        self.open_cost = st.get("open_cost", 0.0)
        self.peak_open_cost = st.get("peak_open_cost", 0.0)
