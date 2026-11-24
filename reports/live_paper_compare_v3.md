# Live paper trading - variant comparison (same live feed)

Generated 2026-11-24 18:49:20 UTC. No real orders were sent.

| variant | markets | latency | fast / fade | PnL | PnL / buys | win rate | bought | maker / taker | fast cancels | fees |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| base | BTC 5m, ETH 5m, BTC 15m | 1.00s | no / 0.000 | $+120.70 | 2.39% | 52.6% | $5,046 | 622 / 293 | 0 | $34.61 |
| btc_taker05_fast | BTC 5m, BTC 15m | 0.30s | no / 0.000 | $+420.13 | 19.61% | 54.5% | $2,142 | 0 / 303 | 0 | $63.48 |
| v3_taker_fast | BTC 5m, BTC 15m | 0.30s | yes / 0.000 | $+775.21 | 33.95% | 68.2% | $2,283 | 0 / 329 | 0 | $70.08 |
| v3_mm_fast | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.000 | $+858.68 | 15.74% | 64.9% | $5,454 | 141 / 723 | 0 | $103.87 |
| v3_mm_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+805.85 | 15.31% | 64.9% | $5,263 | 103 / 720 | 3054 | $102.34 |
| v3_mm_fade_tight | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+786.36 | 12.97% | 62.2% | $6,062 | 253 / 712 | 3080 | $100.69 |
| v3_maker_only_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $-115.30 | -12.27% | 50.0% | $939 | 148 / 0 | 3744 | $0.00 |

Forecast quality (log-loss): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}
