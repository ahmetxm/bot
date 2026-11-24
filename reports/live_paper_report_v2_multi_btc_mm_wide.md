# Live paper trading - strategy replica - variant btc_mm_wide

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 1.00 s, decision every 1.00 s, markets ['BTC 5m', 'BTC 15m']
- Starting balance: $10,000.00 -> final equity $9,997.16
- Realized PnL: $-2.84 over 7 settled markets (2 with fills)
- Win rate (traded markets): 50.0%
- Bought $118.29; PnL / buys: -2.40%
- Fills: 1 maker / 7 taker, fees $1.09
- Unsettled at report time: 3 (cost basis $69.89)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 5m | 2 | $-2.84 | 50.0% | -2.40% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795532400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 4 |
| btc-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 192 |
| btc-updown-15m-1795533300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 706 |
| btc-updown-5m-1795533300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1464 |
| btc-updown-5m-1795533600 | $+15.07 | 0 | 5 | $83.25 | 75.0 | 0.0 | 1626 |
| btc-updown-5m-1795533900 | $-17.91 | 1 | 2 | $35.04 | 50.0 | 17.5 | 2504 |
| btc-updown-5m-1795534200 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1096 |
