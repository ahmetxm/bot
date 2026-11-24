# Live paper trading - strategy replica - variant v3_mm_fade_tight

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.20 s, markets ['BTC 5m', 'ETH 5m', 'BTC 15m']
- Fast (futures) fair value: True; fade threshold 0.010 -> 3080 fast cancels; fills on quotes already being cancelled: 151
- Starting balance: $10,000.00 -> final equity $10,786.36
- Realized PnL: $+786.36 over 38 settled markets (37 with fills)
- Win rate (traded markets): 62.2%
- Bought $6,062.17; PnL / buys: 12.97%
- Fills: 253 maker / 712 taker, fees $100.69
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 6 | $+195.70 | 66.7% | 28.45% |
| BTC 5m | 16 | $+545.95 | 68.8% | 17.76% |
| ETH 5m | 15 | $+44.71 | 53.3% | 1.94% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $-14.33 | 0 | 8 | $19.25 | 150.0 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-34.41 | 2 | 6 | $33.39 | 0.0 | 160.8 | 442 |
| eth-updown-5m-1795541100 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 60 |
| btc-updown-15m-1795541400 | $+36.46 | 1 | 8 | $131.79 | 169.7 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+18.89 | 4 | 5 | $128.07 | 111.2 | 0.0 | 1189 |
| eth-updown-5m-1795541400 | $+30.74 | 2 | 8 | $135.09 | 166.0 | 0.0 | 205 |
| btc-updown-5m-1795541700 | $-16.86 | 25 | 26 | $221.21 | 299.8 | 135.6 | 1986 |
| eth-updown-5m-1795541700 | $+60.93 | 4 | 36 | $275.25 | 190.7 | 20.0 | 413 |
| btc-updown-5m-1795542000 | $+10.58 | 15 | 20 | $143.94 | 66.7 | 200.7 | 1402 |
| eth-updown-5m-1795542000 | $-53.85 | 5 | 27 | $160.33 | 171.7 | 6.9 | 442 |
| btc-updown-15m-1795542300 | $+98.19 | 3 | 8 | $63.05 | 151.9 | 0.9 | 754 |
| btc-updown-5m-1795542300 | $+82.09 | 15 | 36 | $380.82 | 118.8 | 274.4 | 1225 |
| eth-updown-5m-1795542300 | $-64.98 | 0 | 8 | $64.59 | 160.0 | 0.0 | 164 |
| btc-updown-5m-1795542600 | $+66.61 | 12 | 11 | $205.24 | 113.0 | 275.0 | 891 |
| eth-updown-5m-1795542600 | $+6.39 | 2 | 2 | $45.55 | 25.0 | 52.0 | 187 |
| btc-updown-5m-1795542900 | $-34.91 | 7 | 2 | $34.40 | 0.0 | 116.9 | 583 |
| eth-updown-5m-1795542900 | $-26.15 | 1 | 3 | $25.99 | 0.0 | 82.3 | 89 |
| btc-updown-15m-1795543200 | $+30.93 | 1 | 49 | $270.82 | 150.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+4.41 | 2 | 15 | $210.10 | 182.5 | 0.0 | 960 |
| eth-updown-5m-1795543200 | $+42.78 | 4 | 13 | $146.11 | 167.5 | 0.0 | 495 |
| btc-updown-5m-1795543500 | $+26.07 | 6 | 9 | $101.97 | 53.9 | 103.9 | 721 |
| eth-updown-5m-1795543500 | $-43.32 | 4 | 10 | $76.11 | 138.3 | 5.0 | 179 |
| btc-updown-5m-1795543800 | $-4.31 | 2 | 26 | $155.38 | 201.4 | 26.4 | 910 |
| eth-updown-5m-1795543800 | $-18.00 | 7 | 30 | $119.37 | 141.0 | 5.4 | 370 |
| btc-updown-15m-1795544100 | $-48.82 | 1 | 11 | $62.20 | 172.0 | 0.0 | 659 |
| btc-updown-5m-1795544100 | $-67.84 | 13 | 12 | $144.28 | 225.4 | 58.0 | 1540 |
| eth-updown-5m-1795544100 | $+45.00 | 9 | 33 | $232.72 | 88.3 | 161.3 | 315 |
| btc-updown-5m-1795544400 | $+181.33 | 32 | 47 | $331.30 | 199.3 | 332.7 | 2035 |
| eth-updown-5m-1795544400 | $-142.24 | 3 | 29 | $218.17 | 167.0 | 1.6 | 269 |
| btc-updown-5m-1795544700 | $+94.96 | 8 | 13 | $174.41 | 218.1 | 25.5 | 1455 |
| eth-updown-5m-1795544700 | $+112.01 | 3 | 45 | $308.13 | 174.5 | 0.0 | 420 |
| btc-updown-15m-1795545000 | $+93.27 | 0 | 23 | $140.80 | 0.0 | 174.0 | 743 |
| btc-updown-5m-1795545000 | $+48.68 | 11 | 41 | $363.20 | 56.3 | 205.4 | 1723 |
| eth-updown-5m-1795545000 | $+43.06 | 0 | 11 | $150.30 | 173.2 | 0.0 | 284 |
| btc-updown-5m-1795545300 | $+86.30 | 27 | 8 | $175.57 | 263.9 | 107.2 | 1387 |
| eth-updown-5m-1795545300 | $-20.94 | 4 | 43 | $246.75 | 69.3 | 24.3 | 351 |
| btc-updown-5m-1795545600 | $+84.37 | 17 | 21 | $270.98 | 162.5 | 315.4 | 820 |
| eth-updown-5m-1795545600 | $+73.28 | 1 | 9 | $95.52 | 0.0 | 169.2 | 151 |
