# Strategy replica backtest

Generated 2026-11-24 04:57:44 UTC. Data: 3052 resolved crypto Up/Down markets 2026-11-20 04:30:00 UTC -> 2026-11-24 03:55:00 UTC; calibration on the first 1831 (until 2026-11-22 13:45:00 UTC), out-of-sample test on the last 1221.

Starting balance $10,000, budget per market $400, daily loss halt applied. Fill assumptions: {'queue_fill_fraction': 0.0, 'taker_share_of_print': 0.5, 'latency_seconds': 1, 'maker_rebate_rate': 0.0, 'tape_timestamp_lag': 'measured distribution, 202 samples'}.

## Results

| run | markets | PnL | ROI | win rate | PnL / buys | max DD | Sharpe | maker/taker fills | fees |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train (in-sample, chosen params) | 1201 | $9,497.56 | 94.98% | 54.5% | 9.01% | $884 | 22.1 | 13295/15046 | $609.49 |
| **test (out-of-sample, chosen params)** | 1044 | $5,175.20 | 51.75% | 55.5% | 5.51% | $773 | 47.6 | 11216/12883 | $652.42 |
| test - best params, all categories | 1189 | $4,978.44 | 49.78% | 55.5% | 4.94% | $893 | 57.3 | 12004/13714 | $662.26 |
| test - config.yaml defaults | 761 | $3,632.89 | 36.33% | 52.8% | 3.18% | $756 | 48.5 | 21132/9029 | $489.12 |

Target wallet reference (Mar 2026, 7 days): PnL / buys 1.71%, win rate 50.6%, median pair cost 0.918, two-sided 93.9%, 78% maker fills.

Replica behaviour (test): median pair cost 0.914016560089647, two-sided 66.1%, median balance 0.14446415587265649.

## Chosen parameters

```json
{
 "markets": [
  "BTC 5m",
  "ETH 5m",
  "BTC 15m"
 ],
 "vol_halflife_seconds": 600,
 "vol_multiplier": 1.0,
 "vol_floor_bps_per_sqrt_s": 0.35,
 "half_spread": 0.05,
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
 "guard_move": 0.02,
 "take_enabled": true,
 "take_edge": 0.04,
 "take_shares": 25,
 "max_market_usd": 400
}
```

## Fair-value accuracy (log-loss, lower is better)

| model | log-loss |
|---|---:|
| 0.8 | 0.4116 |
| 1.0 | 0.4070 |
| 1.25 | 0.4127 |
| 1.5 | 0.4231 |
| 2.0 | 0.4465 |
| market_last_print | 0.4057 |

## Robustness (test period): how late are the trade timestamps?

The Data API stamps trades ~1-3.5 s after the real match (measured live). The result depends heavily on this delay: a fixed 3 s shift removes all look-ahead but is pessimistic for maker quotes; the random measured delay can be optimistic. **Treat the backtest as inconclusive unless both are positive.**

| delay model | chosen params PnL | PnL / buys | maker-only PnL | PnL / buys |
|---|---:|---:|---:|---:|
| measured random delay (main result) | $5,175 | 5.51% | $2,320 | 3.73% |
| fixed 2 s delay | $1,243 | 2.02% | $-97 | -0.28% |
| fixed 3 s delay (no look-ahead) | $-1,646 | -5.47% | $-1,513 | -7.74% |
| fixed 3 s delay + 2 s latency | $-1,624 | -6.21% | $-1,601 | -8.88% |

## Test by category

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 148 | $248.38 | 62.8% | 1.92% |
| BTC 5m | 457 | $5,292.43 | 55.4% | 8.68% |
| ETH 15m | 145 | $-196.77 | 55.9% | -2.86% |
| ETH 5m | 439 | $-365.60 | 53.1% | -1.83% |

## Daily PnL (test)

| day | PnL |
|---|---:|
| 2026-11-22 | $1,768.76 |
| 2026-11-23 | $2,550.68 |
| 2026-11-24 | $855.76 |

Chart: `charts/strategy_equity.png`. Grid results: `strategy_backtest.json`.
