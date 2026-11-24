# Live paper trading - variant comparison (same live feed)

Generated 2026-11-24 15:43:07 UTC. No real orders were sent.

| variant | markets | latency | PnL | PnL / buys | win rate | bought | maker / taker | fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| base | BTC 5m, ETH 5m, BTC 15m | 1.00s | $+29.53 | 5.58% | 57.1% | $529 | 2 / 44 | $3.90 |
| btc_taker05 | BTC 5m, BTC 15m | 1.00s | $-12.84 | -11.59% | 50.0% | $111 | 0 / 7 | $1.09 |
| btc_taker05_fast | BTC 5m, BTC 15m | 0.30s | $+40.17 | 11.85% | 80.0% | $339 | 0 / 36 | $5.42 |
| btc_taker08_fast | BTC 5m, BTC 15m | 0.30s | $-13.07 | -24.21% | 0.0% | $54 | 0 / 7 | $1.35 |
| btc5_taker05_fast | BTC 5m | 0.30s | $+42.33 | 12.57% | 100.0% | $337 | 0 / 35 | $5.35 |
| btc15_taker05_fast | BTC 15m | 0.30s | $-2.17 | -103.05% | 0.0% | $2 | 0 / 1 | $0.06 |
| btc_mm_wide | BTC 5m, BTC 15m | 1.00s | $-2.84 | -2.40% | 50.0% | $118 | 1 / 7 | $1.09 |

Forecast quality (log-loss): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}
