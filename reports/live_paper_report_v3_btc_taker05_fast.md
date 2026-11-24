# Live paper trading - strategy replica - variant btc_taker05_fast

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.30 s, markets ['BTC 5m', 'BTC 15m']
- Fast (futures) fair value: False; fade threshold 0.000 -> 0 fast cancels; fills on quotes already being cancelled: 0
- Starting balance: $10,000.00 -> final equity $10,420.13
- Realized PnL: $+420.13 over 22 settled markets (22 with fills)
- Win rate (traded markets): 54.5%
- Bought $2,142.24; PnL / buys: 19.61%
- Fills: 0 maker / 303 taker, fees $63.48
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 6 | $+146.91 | 50.0% | 29.67% |
| BTC 5m | 16 | $+273.22 | 56.2% | 16.59% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $-18.56 | 0 | 8 | $21.00 | 160.4 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-20.40 | 0 | 5 | $19.59 | 0.0 | 117.1 | 442 |
| btc-updown-15m-1795541400 | $+25.78 | 0 | 7 | $91.89 | 118.7 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+15.05 | 0 | 6 | $134.25 | 150.0 | 0.0 | 1189 |
| btc-updown-5m-1795541700 | $-40.83 | 0 | 9 | $52.00 | 155.0 | 0.0 | 1986 |
| btc-updown-5m-1795542000 | $-12.43 | 0 | 28 | $155.80 | 0.0 | 140.1 | 1402 |
| btc-updown-15m-1795542300 | $+97.73 | 0 | 9 | $51.65 | 151.0 | 0.0 | 754 |
| btc-updown-5m-1795542300 | $+27.64 | 0 | 14 | $166.80 | 0.0 | 150.0 | 1225 |
| btc-updown-5m-1795542600 | $+59.26 | 0 | 7 | $93.90 | 0.0 | 155.0 | 891 |
| btc-updown-5m-1795542900 | $-7.25 | 0 | 1 | $7.00 | 0.0 | 25.0 | 583 |
| btc-updown-15m-1795543200 | $-17.27 | 0 | 42 | $239.19 | 160.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+32.21 | 0 | 8 | $123.00 | 150.0 | 0.0 | 960 |
| btc-updown-5m-1795543500 | $+14.32 | 0 | 6 | $37.75 | 0.0 | 25.0 | 721 |
| btc-updown-5m-1795543800 | $+17.97 | 0 | 27 | $131.67 | 154.0 | 0.0 | 910 |
| btc-updown-15m-1795544100 | $-56.85 | 0 | 7 | $55.05 | 170.0 | 0.0 | 659 |
| btc-updown-5m-1795544100 | $-20.40 | 0 | 7 | $19.69 | 111.0 | 0.0 | 1540 |
| btc-updown-5m-1795544400 | $-12.06 | 0 | 34 | $169.68 | 57.8 | 0.0 | 2035 |
| btc-updown-5m-1795544700 | $+41.95 | 0 | 10 | $113.69 | 150.0 | 0.0 | 1455 |
| btc-updown-15m-1795545000 | $+116.07 | 0 | 8 | $36.35 | 0.0 | 150.0 | 743 |
| btc-updown-5m-1795545000 | $-12.75 | 0 | 44 | $293.99 | 0.0 | 49.4 | 1723 |
| btc-updown-5m-1795545300 | $+99.23 | 0 | 8 | $60.29 | 161.3 | 0.0 | 1387 |
| btc-updown-5m-1795545600 | $+91.72 | 0 | 8 | $68.00 | 0.0 | 150.0 | 820 |
