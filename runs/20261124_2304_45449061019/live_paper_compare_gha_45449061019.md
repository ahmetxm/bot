# Live paper trading - variant comparison (same live feed)

Generated 2026-11-24 23:04:33 UTC. No real orders were sent.

| variant | markets | latency | fast / fade | PnL | PnL / buys | win rate | bought | maker / taker | fast cancels | fees |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| base | BTC 5m, ETH 5m, BTC 15m | 1.00s | no / 0.000 | $-329.82 | -2.75% | 52.4% | $11,978 | 1131 / 712 | 0 | $86.06 |
| btc_taker05_fast | BTC 5m, BTC 15m | 0.30s | no / 0.000 | $+1,094.29 | 9.98% | 59.8% | $10,960 | 0 / 1336 | 0 | $303.12 |
| v3_taker_fast | BTC 5m, BTC 15m | 0.30s | yes / 0.000 | $+1,986.94 | 18.06% | 72.0% | $11,002 | 0 / 1318 | 0 | $291.08 |
| v3_mm_fast | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.000 | $+1,362.09 | 5.58% | 59.1% | $24,417 | 601 / 2677 | 0 | $408.48 |
| v3_mm_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+1,382.64 | 5.86% | 59.1% | $23,582 | 442 / 2676 | 7958 | $409.81 |
| v3_mm_fade_tight | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+1,361.95 | 5.28% | 57.7% | $25,814 | 1002 / 2609 | 7987 | $393.55 |
| v3_maker_only_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $-350.24 | -4.65% | 57.7% | $7,531 | 1024 / 0 | 10102 | $0.00 |

Forecast quality (log-loss): {'fair_value': 0.5234019967627733, 'market_mid': 0.5163898701884212, 'samples': 4906, 'fast_vs_spot_same_samples': {'spot': 0.5234019967627733, 'fast': 0.5227566032593722, 'samples': 4906}}
