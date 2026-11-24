# Live paper trading - strategy replica - variant btc5_taker05_fast

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, markets ['BTC 5m']
- Starting balance: $10,000.00 -> final equity $10,042.33
- Realized PnL: $+42.33 over 5 settled markets (4 with fills)
- Win rate (traded markets): 100.0%
- Bought $336.74; PnL / buys: 12.57%
- Fills: 0 maker / 35 taker, fees $5.35
- Unsettled at report time: 2 (cost basis $34.01)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 5m | 4 | $+42.33 | 100.0% | 12.57% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 192 |
| btc-updown-5m-1795533300 | $+17.72 | 0 | 5 | $80.30 | 0.0 | 98.7 | 1464 |
| btc-updown-5m-1795533600 | $+13.72 | 0 | 13 | $139.38 | 39.5 | 0.0 | 1626 |
| btc-updown-5m-1795533900 | $+6.10 | 0 | 16 | $97.07 | 0.0 | 30.4 | 2504 |
| btc-updown-5m-1795534200 | $+4.80 | 0 | 1 | $20.00 | 25.0 | 0.0 | 1096 |
