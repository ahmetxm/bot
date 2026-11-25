# Live paper trading - variant comparison (same live feed)

Generated 2026-11-25 04:34:20 UTC. No real orders were sent.

| variant | markets | latency | fast / fade | PnL | PnL / buys | win rate | bought | maker / taker | fast cancels | fees |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| base | BTC 5m, ETH 5m, BTC 15m | 1.00s | no / 0.000 | $-699.80 | -3.49% | 53.9% | $20,029 | 1977 / 1362 | 0 | $186.74 |
| btc_taker05_fast | BTC 5m, BTC 15m | 0.30s | no / 0.000 | $+1,736.13 | 15.01% | 66.3% | $11,569 | 0 / 1402 | 0 | $306.06 |
| v3_taker_fast | BTC 5m, BTC 15m | 0.30s | yes / 0.000 | $+1,878.90 | 16.62% | 69.8% | $11,308 | 0 / 1373 | 0 | $298.46 |
| v3_mm_fast | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.000 | $+1,907.29 | 8.44% | 62.0% | $22,604 | 493 / 2583 | 0 | $405.12 |
| v3_mm_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+1,941.89 | 8.82% | 62.7% | $22,027 | 376 / 2579 | 9366 | $404.71 |
| v3_mm_fade_tight | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+2,162.15 | 8.79% | 62.5% | $24,584 | 978 / 2506 | 9463 | $393.20 |
| v3_maker_only_fade | BTC 5m, ETH 5m, BTC 15m | 0.30s | yes / 0.010 | $+545.21 | 8.13% | 64.7% | $6,707 | 827 / 0 | 11593 | $0.00 |

Forecast quality (log-loss): {'fair_value': 0.4987988968232944, 'market_mid': 0.4951036934180426, 'samples': 4783, 'fast_vs_spot_same_samples': {'spot': 0.4987988968232944, 'fast': 0.4976206094538886, 'samples': 4783}}
