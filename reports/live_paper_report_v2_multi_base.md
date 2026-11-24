# Live paper trading - strategy replica - variant base

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 1.00 s, decision every 1.00 s, markets ['BTC 5m', 'ETH 5m', 'BTC 15m']
- Starting balance: $10,000.00 -> final equity $10,029.53
- Realized PnL: $+29.53 over 12 settled markets (7 with fills)
- Win rate (traded markets): 57.1%
- Bought $529.41; PnL / buys: 5.58%
- Fills: 2 maker / 44 taker, fees $3.90
- Unsettled at report time: 5 (cost basis $93.68)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 1 | $-0.13 | 0.0% | -0.34% |
| BTC 5m | 3 | $-15.09 | 66.7% | -7.05% |
| ETH 5m | 3 | $+44.75 | 66.7% | 16.12% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795532400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 4 |
| btc-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 192 |
| eth-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 33 |
| btc-updown-15m-1795533300 | $-0.13 | 0 | 4 | $38.00 | 0.0 | 0.0 | 706 |
| btc-updown-5m-1795533300 | $+1.91 | 0 | 1 | $23.00 | 0.0 | 25.0 | 1464 |
| eth-updown-5m-1795533300 | $+38.40 | 0 | 9 | $129.37 | 0.0 | 168.0 | 221 |
| btc-updown-5m-1795533600 | $+15.60 | 1 | 8 | $128.85 | 100.0 | 5.0 | 1626 |
| eth-updown-5m-1795533600 | $+36.72 | 0 | 7 | $118.00 | 155.0 | 0.0 | 243 |
| btc-updown-5m-1795533900 | $-32.60 | 1 | 6 | $62.04 | 75.0 | 17.5 | 2504 |
| eth-updown-5m-1795533900 | $-30.37 | 0 | 9 | $30.15 | 0.0 | 150.0 | 402 |
| btc-updown-5m-1795534200 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1096 |
| eth-updown-5m-1795534200 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 106 |
