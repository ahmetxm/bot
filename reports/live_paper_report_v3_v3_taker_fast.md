# Live paper trading - strategy replica - variant v3_taker_fast

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.30 s, markets ['BTC 5m', 'BTC 15m']
- Fast (futures) fair value: True; fade threshold 0.000 -> 0 fast cancels; fills on quotes already being cancelled: 0
- Starting balance: $10,000.00 -> final equity $10,775.21
- Realized PnL: $+775.21 over 22 settled markets (22 with fills)
- Win rate (traded markets): 68.2%
- Bought $2,283.43; PnL / buys: 33.95%
- Fills: 0 maker / 329 taker, fees $70.08
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 6 | $+171.86 | 50.0% | 32.07% |
| BTC 5m | 16 | $+603.34 | 75.0% | 34.53% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $-18.56 | 0 | 8 | $21.00 | 160.4 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-22.13 | 0 | 5 | $21.29 | 0.0 | 105.8 | 442 |
| btc-updown-15m-1795541400 | $+33.85 | 0 | 8 | $127.48 | 162.7 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+17.09 | 0 | 7 | $153.38 | 171.3 | 0.0 | 1189 |
| btc-updown-5m-1795541700 | $-25.28 | 0 | 14 | $51.75 | 150.0 | 0.0 | 1986 |
| btc-updown-5m-1795542000 | $+40.60 | 0 | 11 | $87.25 | 60.1 | 0.0 | 1402 |
| btc-updown-15m-1795542300 | $+91.71 | 0 | 10 | $72.40 | 166.0 | 0.0 | 754 |
| btc-updown-5m-1795542300 | $+84.49 | 0 | 25 | $207.00 | 0.0 | 170.0 | 1225 |
| btc-updown-5m-1795542600 | $+58.95 | 0 | 6 | $89.25 | 0.0 | 150.0 | 891 |
| btc-updown-5m-1795542900 | $-7.25 | 0 | 1 | $7.00 | 0.0 | 25.0 | 583 |
| btc-updown-15m-1795543200 | $-21.70 | 0 | 40 | $224.89 | 175.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+32.05 | 0 | 12 | $143.60 | 157.5 | 0.0 | 960 |
| btc-updown-5m-1795543500 | $+1.43 | 0 | 8 | $32.13 | 0.0 | 0.0 | 721 |
| btc-updown-5m-1795543800 | $+22.66 | 0 | 27 | $119.32 | 159.0 | 0.0 | 910 |
| btc-updown-15m-1795544100 | $-19.28 | 0 | 6 | $33.55 | 62.0 | 0.0 | 659 |
| btc-updown-5m-1795544100 | $-56.55 | 0 | 10 | $68.40 | 127.7 | 0.0 | 1540 |
| btc-updown-5m-1795544400 | $+173.69 | 0 | 50 | $196.42 | 0.0 | 102.6 | 2035 |
| btc-updown-5m-1795544700 | $+54.76 | 0 | 14 | $149.84 | 154.7 | 0.0 | 1455 |
| btc-updown-15m-1795545000 | $+105.84 | 0 | 10 | $56.60 | 0.0 | 150.0 | 743 |
| btc-updown-5m-1795545000 | $+45.77 | 0 | 43 | $293.11 | 0.0 | 130.9 | 1723 |
| btc-updown-5m-1795545300 | $+90.48 | 0 | 6 | $57.75 | 150.0 | 0.0 | 1387 |
| btc-updown-5m-1795545600 | $+92.60 | 0 | 8 | $70.00 | 0.0 | 150.0 | 820 |
