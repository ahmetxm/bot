"""Fair probability that a crypto Up/Down market resolves "Up", from the spot price.

Current Polymarket crypto Up/Down markets resolve on a Chainlink TWAP (`twapLookbackSeconds`,
60 s today): Up  <=>  TWAP(last L s of the window) >= TWAP(last L s before the window start).
Model: log-price is a driftless Brownian motion with an EWMA volatility estimate (x a fat-tail
multiplier). During the final L seconds part of the closing TWAP is already known, which
shrinks the remaining variance (variance of the average of a Brownian path over tau seconds is
sigma^2 * tau / 3).

The same vectorised function is used by the backtest (whole window at once) and the live bot
(a single second), so both see identical fair values.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
from scipy.signal import lfilter
from scipy.special import ndtr


def ewma_variance(log_closes: np.ndarray, halflife_s: float) -> np.ndarray:
    """EWMA of squared 1-second log returns (same length as input, var[0] = var[1])."""
    r2 = np.square(np.diff(log_closes))
    if len(r2) == 0:
        return np.zeros_like(log_closes)
    lam = 0.5 ** (1.0 / max(halflife_s, 1.0))
    init = float(np.mean(r2[: min(len(r2), 600)]))
    var, _ = lfilter([1.0 - lam], [1.0, -lam], r2, zi=[lam * init])
    return np.concatenate([[var[0]], var])


def fair_up_series(log_closes: np.ndarray, ewvar: np.ndarray, t0: int, ws: int, we: int,
                   t_from: int, t_to: int, twap_s: int, vol_mult: float,
                   vol_floor: float) -> np.ndarray:
    """P(Up) for every integer second t in [t_from, t_to].

    log_closes / ewvar are dense per-second arrays starting at epoch t0.
    vol_floor is in log-return units per sqrt(second) (e.g. 0.35e-4).
    """
    n = len(log_closes)

    def idx(t):
        return np.clip(np.asarray(t) - t0, 0, n - 1)

    ts = np.arange(t_from, t_to + 1)
    ls = log_closes[idx(ts)]
    sig = np.maximum(np.sqrt(ewvar[idx(ts)]) * vol_mult, vol_floor)
    tau = (we - ts).astype(np.float64)

    if twap_s > 0:
        ref = float(np.mean(log_closes[idx(np.arange(ws - twap_s + 1, ws + 1))]))
        L = float(twap_s)
        # cumulative known part of the closing TWAP (seconds we-L+1 .. t)
        c0 = we - twap_s + 1
        known_sum = np.zeros_like(ls)
        in_twap = ts >= c0
        if in_twap.any():
            seg = log_closes[idx(np.arange(c0, t_to + 1))]
            cs = np.cumsum(seg)
            known_sum[in_twap] = cs[ts[in_twap] - c0]
        k = np.where(in_twap, ts - c0 + 1, 0).astype(np.float64)    # known seconds
        rem = np.where(in_twap, L - k, 0.0)                          # unknown seconds of the TWAP
        mean_far = ls - ref
        var_far = sig ** 2 * (np.maximum(tau - L, 0.0) + L / 3.0)
        mean_in = (known_sum + rem * ls) / L - ref
        var_in = sig ** 2 * (rem / L) ** 2 * rem / 3.0
        mean = np.where(in_twap, mean_in, mean_far)
        var = np.where(in_twap, var_in, var_far)
    else:
        ref = float(log_closes[idx(ws)])
        mean = ls - ref
        var = sig ** 2 * np.maximum(tau, 0.0)

    sd = np.sqrt(np.maximum(var, 1e-18))
    p = np.where(var > 1e-16, ndtr(mean / sd), np.where(mean >= 0, 1.0, 0.0))
    return np.clip(p, 0.001, 0.999)


class LiveFairValue:
    """Incremental version for the live bot: keeps a rolling 1-second spot buffer."""

    def __init__(self, halflife_s: float, vol_mult: float, vol_floor: float, keep_s: int = 7200):
        self.halflife = halflife_s
        self.vol_mult = vol_mult
        self.vol_floor = vol_floor
        self.keep = keep_s
        self.t0: int | None = None
        self.logs: list[float] = []

    def seed(self, t0: int, closes: np.ndarray) -> None:
        self.t0 = int(t0)
        self.logs = list(np.log(closes.astype(np.float64)))

    def update(self, t: int, price: float) -> None:
        if price <= 0:
            return
        if self.t0 is None:
            self.t0, self.logs = int(t), [math.log(price)]
            return
        last_t = self.t0 + len(self.logs) - 1
        if t <= last_t:
            if t == last_t:          # newer print within the same second -> keep the latest close
                self.logs[-1] = math.log(price)
            return
        gap = t - last_t
        self.logs.extend([self.logs[-1]] * (gap - 1) + [math.log(price)])
        if len(self.logs) > self.keep + 600:
            drop = len(self.logs) - self.keep
            self.logs = self.logs[drop:]
            self.t0 += drop

    @property
    def last_t(self) -> int:
        return (self.t0 or 0) + len(self.logs) - 1

    def p_up(self, t: int, ws: int, we: int, twap_s: int,
             shift: "Callable[[int, int], np.ndarray] | None" = None) -> float | None:
        """shift(t0, n) -> per-second log offsets added to the series (e.g. Chainlink-Binance basis)."""
        if self.t0 is None or len(self.logs) < 120 or ws - twap_s < self.t0:
            return None
        arr = np.asarray(self.logs)
        ev = ewma_variance(arr, self.halflife)
        if shift is not None:
            arr = arr + shift(self.t0, len(arr))
        t = min(t, self.last_t)
        return float(fair_up_series(arr, ev, self.t0, ws, we, t, t, twap_s,
                                    self.vol_mult, self.vol_floor)[0])
