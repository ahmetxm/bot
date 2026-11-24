# Strategy replica backtest

Generated 2026-11-24 14:49:48 UTC. Data: 2736 resolved crypto Up/Down markets 2026-11-20 14:20:00 UTC -> 2026-11-24 03:55:00 UTC; calibration on the first 1641 (until 2026-11-22 17:40:00 UTC), out-of-sample test on the last 1095.

Starting balance $10,000, budget per market $400, daily loss halt applied. Fill assumptions: {'queue_fill_fraction': 0.0, 'taker_share_of_print': 0.5, 'latency_seconds': 1, 'maker_rebate_rate': 0.0, 'tape_timestamp_lag': 'measured distribution, 202 samples'}.

Parameter selection and train/test rows use tape delay model: **fixed3** (fixed3 = every print shifted 3 s earlier, no look-ahead). Grid: v2.

## Results

| run | markets | PnL | ROI | win rate | PnL / buys | max DD | Sharpe | maker/taker fills | fees |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train (in-sample, chosen params) | 660 | $1,735.63 | 17.36% | 49.1% | 7.76% | $593 | 15.2 | 0/7858 | $461.40 |
| **test (out-of-sample, chosen params)** | 365 | $-359.54 | -3.60% | 50.1% | -2.33% | $905 | -7.4 | 0/5164 | $297.62 |
| test - best params, all categories | 575 | $-625.72 | -6.26% | 52.9% | -3.52% | $1,021 | -14.2 | 0/6012 | $269.31 |
| test - config.yaml defaults | 139 | $-1,276.17 | -12.76% | 42.4% | -7.18% | $1,332 | -49.0 | 3987/745 | $36.91 |

Target wallet reference (Mar 2026, 7 days): PnL / buys 1.71%, win rate 50.6%, median pair cost 0.918, two-sided 93.9%, 78% maker fills.

Replica behaviour (test): median pair cost 0.8804936804801948, two-sided 31.5%, median balance 0.0.

## Chosen parameters

```json
{
 "markets": [
  "BTC 5m",
  "BTC 15m"
 ],
 "vol_halflife_seconds": 600,
 "vol_multiplier": 1.0,
 "vol_floor_bps_per_sqrt_s": 0.35,
 "half_spread": 1.0,
 "inventory_skew": 0.02,
 "max_imbalance_shares": 150,
 "order_shares": 25,
 "pair_cost_cap": 0.98,
 "min_price": 0.05,
 "max_price": 0.95,
 "start_delay_seconds": 5,
 "stop_before_end_seconds": 30,
 "requote_threshold": 0.01,
 "guard_seconds": 3,
 "guard_move": 0.0,
 "take_enabled": true,
 "take_edge": 0.05,
 "take_shares": 25,
 "take_cutoff_frac": 1.0,
 "maker_cutoff_frac": 1.0,
 "max_market_usd": 400
}
```

## Fair-value accuracy (log-loss, lower is better)

| model | log-loss |
|---|---:|
| 0.8 | 0.3777 |
| 1.0 | 0.3775 |
| 1.25 | 0.3843 |
| 1.5 | 0.3953 |
| 2.0 | 0.4190 |
| market_last_print | 0.3871 |

## Robustness (test period): how late are the trade timestamps?

The Data API stamps trades ~1-3.5 s after the real match (measured live). The result depends heavily on this delay: a fixed 3 s shift removes all look-ahead but is pessimistic for maker quotes; the random measured delay can be optimistic. **Treat the backtest as inconclusive unless both are positive.**

| delay model | chosen params PnL | PnL / buys | maker-only PnL | PnL / buys |
|---|---:|---:|---:|---:|
| measured random delay (main result) | $2,210 | 7.35% | $0 | 0.00% |
| fixed 2 s delay | $389 | 2.32% | $0 | 0.00% |
| fixed 3 s delay (no look-ahead) | $-360 | -2.33% | $0 | 0.00% |
| fixed 3 s delay + 2 s latency | $-424 | -2.61% | $0 | 0.00% |

## Test by category

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 68 | $-261.20 | 66.2% | -9.15% |
| BTC 5m | 230 | $163.95 | 49.1% | 1.59% |
| ETH 15m | 74 | $-244.22 | 55.4% | -21.92% |
| ETH 5m | 203 | $-284.25 | 51.7% | -8.20% |

## Daily PnL (test)

| day | PnL |
|---|---:|
| 2026-11-22 | $267.81 |
| 2026-11-23 | $-493.13 |
| 2026-11-24 | $-134.22 |

Chart: `charts/strategy_equity_v2_fixed3.png`. Grid results: `strategy_backtest_v2_fixed3.json`.
