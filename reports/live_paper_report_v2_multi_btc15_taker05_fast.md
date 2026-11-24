# Live paper trading - strategy replica - variant btc15_taker05_fast

Generated 2026-11-24 15:43:07 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, markets ['BTC 15m']
- Starting balance: $10,000.00 -> final equity $9,997.83
- Realized PnL: $-2.17 over 2 settled markets (1 with fills)
- Win rate (traded markets): 0.0%
- Bought $2.10; PnL / buys: -103.05%
- Fills: 0 maker / 1 taker, fees $0.06
- Unsettled at report time: 1 (cost basis $61.58)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.3110977835022987, 'market_mid': 0.3269640154774674, 'samples': 258}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 1 | $-2.17 | 0.0% | -103.05% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795532400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 4 |
| btc-updown-15m-1795533300 | $-2.17 | 0 | 1 | $2.10 | 5.4 | 0.0 | 706 |
