# Live paper trading - strategy replica - variant btc_taker08_fast

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, markets ['BTC 5m', 'BTC 15m']
- Starting balance: $10,000.00 -> final equity $9,986.93
- Realized PnL: $-13.07 over 7 settled markets (1 with fills)
- Win rate (traded markets): 0.0%
- Bought $54.00; PnL / buys: -24.21%
- Fills: 0 maker / 7 taker, fees $1.35
- Unsettled at report time: 3 (cost basis $58.39)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 5m | 1 | $-13.07 | 0.0% | -24.21% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795532400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 4 |
| btc-updown-5m-1795533000 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 192 |
| btc-updown-15m-1795533300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 706 |
| btc-updown-5m-1795533300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1464 |
| btc-updown-5m-1795533600 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1626 |
| btc-updown-5m-1795533900 | $-13.07 | 0 | 7 | $54.00 | 9.6 | 0.0 | 2504 |
| btc-updown-5m-1795534200 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1096 |
