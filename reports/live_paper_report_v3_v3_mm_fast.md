# Live paper trading - strategy replica - variant v3_mm_fast

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.20 s, markets ['BTC 5m', 'ETH 5m', 'BTC 15m']
- Fast (futures) fair value: True; fade threshold 0.000 -> 0 fast cancels; fills on quotes already being cancelled: 100
- Starting balance: $10,000.00 -> final equity $10,858.68
- Realized PnL: $+858.68 over 38 settled markets (37 with fills)
- Win rate (traded markets): 64.9%
- Bought $5,454.48; PnL / buys: 15.74%
- Fills: 141 maker / 723 taker, fees $103.87
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 6 | $+202.11 | 66.7% | 27.62% |
| BTC 5m | 16 | $+550.05 | 75.0% | 21.58% |
| ETH 5m | 15 | $+106.52 | 53.3% | 4.90% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $-14.33 | 0 | 8 | $19.25 | 150.0 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-33.91 | 2 | 6 | $32.89 | 0.0 | 160.8 | 442 |
| eth-updown-5m-1795541100 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 60 |
| btc-updown-15m-1795541400 | $+35.49 | 0 | 8 | $129.53 | 166.5 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+17.06 | 2 | 6 | $124.50 | 105.9 | 0.0 | 1189 |
| eth-updown-5m-1795541400 | $+27.62 | 0 | 9 | $132.40 | 160.2 | 0.0 | 205 |
| btc-updown-5m-1795541700 | $-11.62 | 15 | 29 | $213.02 | 300.1 | 133.3 | 1986 |
| eth-updown-5m-1795541700 | $+73.75 | 7 | 32 | $247.11 | 175.6 | 12.2 | 413 |
| btc-updown-5m-1795542000 | $+11.90 | 8 | 21 | $131.93 | 32.0 | 161.9 | 1402 |
| eth-updown-5m-1795542000 | $-54.77 | 3 | 28 | $160.99 | 171.1 | 6.7 | 442 |
| btc-updown-15m-1795542300 | $+92.10 | 2 | 11 | $87.65 | 155.8 | 0.0 | 754 |
| btc-updown-5m-1795542300 | $+92.38 | 1 | 33 | $276.13 | 25.0 | 172.4 | 1225 |
| eth-updown-5m-1795542300 | $-64.98 | 0 | 8 | $64.59 | 160.0 | 0.0 | 164 |
| btc-updown-5m-1795542600 | $+61.17 | 1 | 7 | $111.75 | 25.0 | 175.0 | 891 |
| eth-updown-5m-1795542600 | $+10.89 | 0 | 2 | $16.05 | 0.0 | 27.0 | 187 |
| btc-updown-5m-1795542900 | $-24.90 | 2 | 2 | $24.40 | 0.0 | 83.0 | 583 |
| eth-updown-5m-1795542900 | $-23.66 | 0 | 3 | $23.50 | 0.0 | 75.0 | 89 |
| btc-updown-15m-1795543200 | $+30.93 | 1 | 49 | $270.82 | 150.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+5.73 | 3 | 15 | $217.03 | 190.8 | 0.0 | 960 |
| eth-updown-5m-1795543200 | $+42.28 | 3 | 13 | $137.90 | 160.5 | 2.9 | 495 |
| btc-updown-5m-1795543500 | $+26.65 | 0 | 9 | $61.38 | 0.0 | 50.0 | 721 |
| eth-updown-5m-1795543500 | $-20.07 | 0 | 10 | $54.79 | 73.0 | 3.0 | 179 |
| btc-updown-5m-1795543800 | $+0.89 | 1 | 27 | $145.81 | 180.1 | 5.1 | 910 |
| eth-updown-5m-1795543800 | $-16.59 | 7 | 29 | $121.71 | 145.0 | 5.0 | 370 |
| btc-updown-15m-1795544100 | $-35.35 | 3 | 12 | $83.60 | 192.0 | 35.0 | 659 |
| btc-updown-5m-1795544100 | $-75.09 | 5 | 12 | $93.53 | 167.6 | 0.0 | 1540 |
| eth-updown-5m-1795544100 | $+64.95 | 4 | 32 | $181.49 | 6.4 | 6.4 | 315 |
| btc-updown-5m-1795544400 | $+145.43 | 16 | 51 | $251.37 | 71.6 | 155.0 | 2035 |
| eth-updown-5m-1795544400 | $-145.16 | 3 | 29 | $221.28 | 167.0 | 0.0 | 269 |
| btc-updown-5m-1795544700 | $+91.14 | 5 | 15 | $155.29 | 195.8 | 23.9 | 1455 |
| eth-updown-5m-1795544700 | $+113.79 | 3 | 47 | $301.28 | 177.5 | 4.5 | 420 |
| btc-updown-15m-1795545000 | $+93.27 | 0 | 23 | $140.80 | 0.0 | 174.0 | 743 |
| btc-updown-5m-1795545000 | $+61.49 | 11 | 42 | $333.77 | 39.7 | 193.7 | 1723 |
| eth-updown-5m-1795545000 | $+42.41 | 1 | 11 | $150.95 | 173.2 | 5.0 | 284 |
| btc-updown-5m-1795545300 | $+84.83 | 20 | 13 | $202.73 | 290.8 | 123.5 | 1387 |
| eth-updown-5m-1795545300 | $-16.19 | 5 | 43 | $267.00 | 94.3 | 24.3 | 351 |
| btc-updown-5m-1795545600 | $+96.89 | 7 | 19 | $173.84 | 61.8 | 215.3 | 820 |
| eth-updown-5m-1795545600 | $+72.24 | 0 | 9 | $92.40 | 0.0 | 165.0 | 151 |
