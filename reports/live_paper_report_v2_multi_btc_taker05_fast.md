# Live paper trading - strategy replica - variant btc_taker05_fast

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, markets ['BTC 5m', 'BTC 15m']
- Starting balance: $10,000.00 -> final equity $10,040.17
- Realized PnL: $+40.17 over 7 settled markets (5 with fills)
- Win rate (traded markets): 80.0%
- Bought $338.85; PnL / buys: 11.85%
- Fills: 0 maker / 36 taker, fees $5.42
- Unsettled at report time: 3 (cost basis $95.60)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 1 | $-2.17 | 0.0% | -103.05% |
| BTC 5m | 4 | $+42.33 | 100.0% | 12.57% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795532400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 4 |
| btc-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 192 |
| btc-updown-15m-1795533300 | $-2.17 | 0 | 1 | $2.10 | 5.4 | 0.0 | 706 |
| btc-updown-5m-1795533300 | $+17.72 | 0 | 5 | $80.30 | 0.0 | 98.7 | 1464 |
| btc-updown-5m-1795533600 | $+13.72 | 0 | 13 | $139.38 | 39.5 | 0.0 | 1626 |
| btc-updown-5m-1795533900 | $+6.10 | 0 | 16 | $97.07 | 0.0 | 30.4 | 2504 |
| btc-updown-5m-1795534200 | $+4.80 | 0 | 1 | $20.00 | 25.0 | 0.0 | 1096 |
