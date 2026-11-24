# Live paper trading - strategy replica - variant v3_maker_only_fade

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.20 s, markets ['BTC 5m', 'ETH 5m', 'BTC 15m']
- Fast (futures) fair value: True; fade threshold 0.010 -> 3744 fast cancels; fills on quotes already being cancelled: 98
- Starting balance: $10,000.00 -> final equity $9,884.70
- Realized PnL: $-115.30 over 38 settled markets (28 with fills)
- Win rate (traded markets): 50.0%
- Bought $939.36; PnL / buys: -12.27%
- Fills: 148 maker / 0 taker, fees $0.00
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 3 | $-49.54 | 66.7% | -61.51% |
| BTC 5m | 13 | $-160.24 | 30.8% | -29.60% |
| ETH 5m | 12 | $+94.48 | 66.7% | 29.77% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-7.35 | 2 | 0 | $7.35 | 0.0 | 30.0 | 442 |
| eth-updown-5m-1795541100 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 60 |
| btc-updown-15m-1795541400 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+10.75 | 2 | 0 | $39.25 | 50.0 | 0.0 | 1189 |
| eth-updown-5m-1795541400 | $+9.86 | 4 | 0 | $61.93 | 71.8 | 0.0 | 205 |
| btc-updown-5m-1795541700 | $-32.32 | 13 | 0 | $62.59 | 105.7 | 30.3 | 1986 |
| eth-updown-5m-1795541700 | $+3.47 | 3 | 0 | $7.60 | 11.1 | 0.0 | 413 |
| btc-updown-5m-1795542000 | $-10.72 | 5 | 0 | $10.72 | 0.0 | 62.2 | 1402 |
| eth-updown-5m-1795542000 | $-4.72 | 2 | 0 | $4.72 | 7.7 | 0.0 | 442 |
| btc-updown-15m-1795542300 | $+17.00 | 1 | 0 | $8.00 | 25.0 | 0.0 | 754 |
| btc-updown-5m-1795542300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 1225 |
| eth-updown-5m-1795542300 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 164 |
| btc-updown-5m-1795542600 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 891 |
| eth-updown-5m-1795542600 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 187 |
| btc-updown-5m-1795542900 | $-10.82 | 3 | 0 | $10.82 | 0.0 | 34.4 | 583 |
| eth-updown-5m-1795542900 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 89 |
| btc-updown-15m-1795543200 | $-69.30 | 5 | 0 | $69.30 | 103.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+25.32 | 7 | 0 | $132.93 | 158.2 | 0.0 | 960 |
| eth-updown-5m-1795543200 | $+40.53 | 11 | 0 | $77.51 | 118.0 | 0.0 | 495 |
| btc-updown-5m-1795543500 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 721 |
| eth-updown-5m-1795543500 | $-4.63 | 1 | 0 | $4.63 | 15.4 | 0.0 | 179 |
| btc-updown-5m-1795543800 | $-12.28 | 10 | 0 | $12.28 | 141.7 | 0.0 | 910 |
| eth-updown-5m-1795543800 | $-19.75 | 5 | 0 | $19.75 | 95.0 | 0.0 | 370 |
| btc-updown-15m-1795544100 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 659 |
| btc-updown-5m-1795544100 | $-32.44 | 7 | 0 | $32.44 | 77.1 | 0.0 | 1540 |
| eth-updown-5m-1795544100 | $+22.21 | 5 | 0 | $32.41 | 54.6 | 5.0 | 315 |
| btc-updown-5m-1795544400 | $+28.42 | 12 | 0 | $45.83 | 31.5 | 74.2 | 2035 |
| eth-updown-5m-1795544400 | $+3.39 | 2 | 0 | $6.88 | 0.0 | 10.3 | 269 |
| btc-updown-5m-1795544700 | $+22.92 | 3 | 0 | $45.50 | 68.4 | 0.0 | 1455 |
| eth-updown-5m-1795544700 | $+41.50 | 9 | 0 | $33.50 | 75.0 | 0.0 | 420 |
| btc-updown-15m-1795545000 | $+2.76 | 1 | 0 | $3.24 | 0.0 | 6.0 | 743 |
| btc-updown-5m-1795545000 | $-94.28 | 11 | 0 | $94.28 | 127.5 | 0.0 | 1723 |
| eth-updown-5m-1795545000 | $+11.94 | 4 | 0 | $54.99 | 66.9 | 0.0 | 284 |
| btc-updown-5m-1795545300 | $-19.86 | 11 | 0 | $19.86 | 0.0 | 48.5 | 1387 |
| eth-updown-5m-1795545300 | $-10.35 | 4 | 0 | $10.35 | 0.0 | 20.3 | 351 |
| btc-updown-5m-1795545600 | $-27.56 | 4 | 0 | $27.56 | 56.9 | 0.0 | 820 |
| eth-updown-5m-1795545600 | $+1.04 | 1 | 0 | $3.12 | 0.0 | 4.2 | 151 |
