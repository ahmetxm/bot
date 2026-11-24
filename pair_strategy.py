"""Strategy replica of the target wallet (k9Q2mX4L8A7ZP3R).

What the target does (see reports/behavior_profile.md, derived from 842k fills):
  * trades only crypto Up/Down 5m/15m/1h markets, inside the window (from ~5 s after start);
  * 78% of fills are passive BUY limit orders on BOTH outcomes (two-sided in 94% of markets),
    priced slightly below a spot-implied fair value (+0.5c edge on average);
  * taker buys follow ~1 bp spot moves in the bought direction within 10 s (latency leg, +1.5c edge);
  * it sells the heavy side after adverse spot moves (inventory control);
  * holds the rest to resolution; median combined Up+Down cost 0.91.

This module is pure decision logic (no I/O). The backtest and the live/paper bot call the same
methods, so they make identical decisions for identical inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Optional


@dataclass
class StrategyParams:
    markets: list = field(default_factory=lambda: ["BTC 5m", "BTC 15m", "ETH 15m"])
    vol_halflife_seconds: float = 600
    vol_multiplier: float = 1.25
    vol_floor_bps_per_sqrt_s: float = 0.35
    half_spread: float = 0.03
    inventory_skew: float = 0.02
    max_imbalance_shares: float = 150
    order_shares: float = 20
    pair_cost_cap: float = 0.98
    min_price: float = 0.05
    max_price: float = 0.95
    start_delay_seconds: int = 5
    stop_before_end_seconds: int = 30
    requote_threshold: float = 0.01
    guard_seconds: int = 3          # adverse-move guard look-back
    guard_move: float = 0.0         # pull a side's bid if its fair fell by more than this (0 = off)
    take_enabled: bool = True
    take_edge: float = 0.04
    take_shares: float = 20
    take_cutoff_frac: float = 1.0    # taker leg only in the first X of the window (1.0 = whole window)
    maker_cutoff_frac: float = 1.0   # resting quotes only in the first X of the window
    max_market_usd: float = 400

    @classmethod
    def from_cfg(cls, cfg: dict, overrides: Optional[dict] = None) -> "StrategyParams":
        src = dict(cfg.get("pair_strategy") or {})
        src.update(overrides or {})
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in src.items() if k in names})

    @property
    def vol_floor(self) -> float:
        return self.vol_floor_bps_per_sqrt_s * 1e-4

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass
class Inventory:
    shares: list = field(default_factory=lambda: [0.0, 0.0])
    cost: list = field(default_factory=lambda: [0.0, 0.0])   # USDC paid (net of sells), excl. fees
    fees: float = 0.0
    rebates: float = 0.0
    maker_fills: int = 0
    taker_fills: int = 0
    buy_usdc: float = 0.0
    sell_usdc: float = 0.0
    buy_shares: list = field(default_factory=lambda: [0.0, 0.0])
    buy_cost: list = field(default_factory=lambda: [0.0, 0.0])

    def avg_cost(self, i: int) -> Optional[float]:
        return self.buy_cost[i] / self.buy_shares[i] if self.buy_shares[i] > 0 else None

    @property
    def cost_basis(self) -> float:
        return self.cost[0] + self.cost[1] + self.fees

    def apply_buy(self, i: int, price: float, shares: float, fee: float, maker: bool, rebate: float = 0.0):
        self.shares[i] += shares
        self.cost[i] += price * shares
        self.buy_shares[i] += shares
        self.buy_cost[i] += price * shares
        self.fees += fee
        self.rebates += rebate
        self.buy_usdc += price * shares
        if maker:
            self.maker_fills += 1
        else:
            self.taker_fills += 1

    def apply_sell(self, i: int, price: float, shares: float, fee: float, maker: bool, rebate: float = 0.0):
        shares = min(shares, self.shares[i])
        if shares <= 0:
            return 0.0
        self.shares[i] -= shares
        self.cost[i] -= price * shares
        self.fees += fee
        self.rebates += rebate
        self.sell_usdc += price * shares
        if maker:
            self.maker_fills += 1
        else:
            self.taker_fills += 1
        return shares

    def settle(self, payouts: list) -> float:
        """Final PnL once the market resolved (payout per share per outcome)."""
        value = self.shares[0] * payouts[0] + self.shares[1] * payouts[1]
        return value - self.cost[0] - self.cost[1] - self.fees + self.rebates

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "Inventory":
        inv = cls()
        for k, v in (d or {}).items():
            if hasattr(inv, k):
                setattr(inv, k, v)
        return inv


def taker_fee_per_share(price: float, fee_rate: float) -> float:
    return fee_rate * price * (1.0 - price)


def floor_tick(p: float, tick: float) -> float:
    return math.floor(p / tick + 1e-9) * tick


def ceil_tick(p: float, tick: float) -> float:
    return math.ceil(p / tick - 1e-9) * tick


class PairStrategy:
    """Decides resting bids (maker leg) and marketable orders (taker leg) for ONE market."""

    def __init__(self, params: StrategyParams, fee_rate: float, tick: float = 0.01,
                 min_size: float = 5.0, budget_usd: Optional[float] = None):
        self.p = params
        self.fee_rate = fee_rate
        # Polymarket's tick is dynamic: 0.001 only once a price is outside 0.04-0.96 (outside our trading
        # range), so metadata captured at resolution can say 0.001 although 0.01 applied while we quote.
        self.tick = max(float(tick or 0.01), 0.01)
        self.min_size = min_size
        self.budget = min(params.max_market_usd, budget_usd) if budget_usd else params.max_market_usd

    def active(self, t: int, ws: int, we: int, cutoff_frac: float = 1.0) -> bool:
        if not ws + self.p.start_delay_seconds <= t <= we - self.p.stop_before_end_seconds:
            return False
        return cutoff_frac >= 1.0 or (t - ws) <= cutoff_frac * (we - ws)

    def _room(self, inv: Inventory, price: float) -> float:
        left = self.budget - inv.cost_basis
        return max(left, 0.0) / max(price, 0.01)

    def quotes(self, t: int, ws: int, we: int, fair_up: float, inv: Inventory,
               best_bid: list, best_ask: list, fair_up_prev: Optional[float] = None) -> dict:
        """Desired resting BUY orders {outcome: (price, shares)} (empty dict = cancel all).

        fair_up_prev = fair value `guard_seconds` ago (for the adverse-move guard)."""
        p = self.p
        if fair_up is None or not self.active(t, ws, we, p.maker_cutoff_frac):
            return {}
        fair = (fair_up, 1.0 - fair_up)
        move_up = (fair_up - fair_up_prev) if fair_up_prev is not None else 0.0
        out = {}
        for i in (0, 1):
            j = 1 - i
            excess = inv.shares[i] - inv.shares[j]
            if excess >= p.max_imbalance_shares:
                continue
            if p.guard_move > 0 and (move_up if i == 1 else -move_up) > p.guard_move:
                continue                                       # this side's fair is collapsing: step away
            frac = max(-1.0, min(1.0, excess / max(p.max_imbalance_shares, 1.0)))
            bid = fair[i] - p.half_spread - p.inventory_skew * frac
            a_j = inv.avg_cost(j)
            if a_j is not None and inv.shares[j] > inv.shares[i]:
                bid = min(bid, p.pair_cost_cap - a_j)          # completing pairs must stay profitable
            bid = floor_tick(bid, self.tick)
            ask = best_ask[i] if best_ask else None
            if ask is not None and bid >= ask - 1e-9:          # post-only: never cross the spread
                bid = floor_tick(ask - self.tick, self.tick)
            if bid < p.min_price or bid > p.max_price:
                continue
            size = min(p.order_shares, self._room(inv, bid))
            if size < self.min_size:
                continue
            out[i] = (round(bid, 4), math.floor(size * 100) / 100)
        return out

    def taker_orders(self, t: int, ws: int, we: int, fair_up: float, inv: Inventory,
                     best_bid: list, best_ask: list) -> list:
        """Marketable orders [(side, outcome, limit_price, shares)] for the latency leg."""
        p = self.p
        if not p.take_enabled or fair_up is None or not self.active(t, ws, we, p.take_cutoff_frac):
            return []
        fair = (fair_up, 1.0 - fair_up)
        orders = []
        for i in (0, 1):
            j = 1 - i
            excess = inv.shares[i] - inv.shares[j]
            ask = best_ask[i] if best_ask else None
            if ask is not None and p.min_price <= ask <= p.max_price and excess < p.max_imbalance_shares:
                if ask + taker_fee_per_share(ask, self.fee_rate) <= fair[i] - p.take_edge:
                    size = min(p.take_shares, self._room(inv, ask))
                    if size >= self.min_size:
                        orders.append(("BUY", i, ask, math.floor(size * 100) / 100))
            bid = best_bid[i] if best_bid else None
            if bid is not None and excess > 0 and inv.shares[i] > 0:
                if bid - taker_fee_per_share(bid, self.fee_rate) >= fair[i] + p.take_edge:
                    size = min(p.take_shares, excess)
                    if size >= self.min_size:
                        orders.append(("SELL", i, bid, math.floor(size * 100) / 100))
        # selling outcome i and buying the other outcome are the same bet (mirrored books): keep only the sell
        sells = {i for side, i, _, _ in orders if side == "SELL"}
        return [o for o in orders if not (o[0] == "BUY" and (1 - o[1]) in sells)]
