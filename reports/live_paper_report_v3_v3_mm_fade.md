# Live paper trading - strategy replica - variant v3_mm_fade

Generated 2026-11-24 18:49:20 UTC. No real orders were sent; fills are simulated against the live Polymarket order book and live trade prints (see live_paper.py docstring).

- Latency 0.30 s, decision every 0.25 s, cancel latency 0.20 s, markets ['BTC 5m', 'ETH 5m', 'BTC 15m']
- Fast (futures) fair value: True; fade threshold 0.010 -> 3054 fast cancels; fills on quotes already being cancelled: 62
- Starting balance: $10,000.00 -> final equity $10,805.85
- Realized PnL: $+805.85 over 38 settled markets (37 with fills)
- Win rate (traded markets): 64.9%
- Bought $5,263.30; PnL / buys: 15.31%
- Fills: 103 maker / 720 taker, fees $102.34
- Unsettled at report time: 0 (cost basis $0.00)
- Forecast quality (log-loss, lower = better; every 10 s while the spread was <= 5c): {'fair_value': 0.5228677304486172, 'market_mid': 0.5199256540430347, 'samples': 1189, 'fast_vs_spot_same_samples': {'spot': 0.5228677304486172, 'fast': 0.521807792792264, 'samples': 1189}}

| category | markets | PnL | win rate | PnL / buys |
|---|---:|---:|---:|---:|
| BTC 15m | 6 | $+186.48 | 66.7% | 26.35% |
| BTC 5m | 16 | $+538.30 | 75.0% | 22.10% |
| ETH 5m | 15 | $+81.08 | 53.3% | 3.82% |

| market | PnL | maker | taker | bought | Up sh | Down sh | prints seen |
|---|---:|---:|---:|---:|---:|---:|---:|
| btc-updown-15m-1795540500 | $-14.33 | 0 | 8 | $19.25 | 150.0 | 0.0 | 617 |
| btc-updown-5m-1795541100 | $-33.91 | 2 | 6 | $32.89 | 0.0 | 160.8 | 442 |
| eth-updown-5m-1795541100 | $+0.00 | 0 | 0 | $0.00 | 0.0 | 0.0 | 60 |
| btc-updown-15m-1795541400 | $+35.49 | 0 | 8 | $129.53 | 166.5 | 0.0 | 419 |
| btc-updown-5m-1795541400 | $+17.06 | 2 | 6 | $124.50 | 105.9 | 0.0 | 1189 |
| eth-updown-5m-1795541400 | $+27.62 | 0 | 9 | $132.40 | 160.2 | 0.0 | 205 |
| btc-updown-5m-1795541700 | $-18.82 | 9 | 28 | $169.01 | 250.1 | 81.8 | 1986 |
| eth-updown-5m-1795541700 | $+70.73 | 2 | 35 | $234.05 | 159.6 | 0.0 | 413 |
| btc-updown-5m-1795542000 | $+25.93 | 5 | 22 | $115.90 | 25.0 | 104.1 | 1402 |
| eth-updown-5m-1795542000 | $-58.79 | 1 | 28 | $158.31 | 171.1 | 0.0 | 442 |
| btc-updown-15m-1795542300 | $+87.94 | 0 | 12 | $87.15 | 166.0 | 0.0 | 754 |
| btc-updown-5m-1795542300 | $+78.43 | 0 | 34 | $269.55 | 0.0 | 147.4 | 1225 |
| eth-updown-5m-1795542300 | $-64.98 | 0 | 8 | $64.59 | 160.0 | 0.0 | 164 |
| btc-updown-5m-1795542600 | $+61.17 | 1 | 7 | $111.75 | 25.0 | 175.0 | 891 |
| eth-updown-5m-1795542600 | $+10.89 | 0 | 2 | $16.05 | 0.0 | 27.0 | 187 |
| btc-updown-5m-1795542900 | $-24.90 | 2 | 2 | $24.40 | 0.0 | 83.0 | 583 |
| eth-updown-5m-1795542900 | $-23.66 | 0 | 3 | $23.50 | 0.0 | 75.0 | 89 |
| btc-updown-15m-1795543200 | $+30.93 | 1 | 49 | $270.82 | 150.0 | 0.0 | 1108 |
| btc-updown-5m-1795543200 | $+5.73 | 3 | 15 | $217.03 | 190.8 | 0.0 | 960 |
| eth-updown-5m-1795543200 | $+31.60 | 2 | 13 | $142.31 | 152.5 | 0.0 | 495 |
| btc-updown-5m-1795543500 | $+26.65 | 0 | 9 | $61.38 | 0.0 | 50.0 | 721 |
| eth-updown-5m-1795543500 | $-20.07 | 0 | 10 | $54.79 | 73.0 | 3.0 | 179 |
| btc-updown-5m-1795543800 | $+4.58 | 0 | 26 | $141.19 | 150.0 | 0.0 | 910 |
| eth-updown-5m-1795543800 | $-16.91 | 5 | 29 | $117.03 | 133.0 | 0.0 | 370 |
| btc-updown-15m-1795544100 | $-46.82 | 0 | 11 | $60.20 | 167.0 | 0.0 | 659 |
| btc-updown-5m-1795544100 | $-75.09 | 5 | 12 | $93.53 | 167.6 | 0.0 | 1540 |
| eth-updown-5m-1795544100 | $+64.95 | 4 | 32 | $181.49 | 6.4 | 6.4 | 315 |
| btc-updown-5m-1795544400 | $+139.69 | 15 | 48 | $246.10 | 74.8 | 158.2 | 2035 |
| eth-updown-5m-1795544400 | $-143.30 | 2 | 29 | $217.62 | 167.0 | 0.0 | 269 |
| btc-updown-5m-1795544700 | $+92.27 | 3 | 15 | $154.16 | 195.8 | 19.2 | 1455 |
| eth-updown-5m-1795544700 | $+108.63 | 1 | 45 | $288.51 | 151.5 | 0.0 | 420 |
| btc-updown-15m-1795545000 | $+93.27 | 0 | 23 | $140.80 | 0.0 | 174.0 | 743 |
| btc-updown-5m-1795545000 | $+54.52 | 8 | 42 | $325.47 | 7.5 | 171.8 | 1723 |
| eth-updown-5m-1795545000 | $+43.06 | 0 | 11 | $150.30 | 173.2 | 0.0 | 284 |
| btc-updown-5m-1795545300 | $+88.10 | 19 | 12 | $174.73 | 265.8 | 98.5 | 1387 |
| eth-updown-5m-1795545300 | $-20.94 | 4 | 43 | $246.75 | 69.3 | 24.3 | 351 |
| btc-updown-5m-1795545600 | $+96.89 | 7 | 19 | $173.84 | 61.8 | 215.3 | 820 |
| eth-updown-5m-1795545600 | $+72.24 | 0 | 9 | $92.40 | 0.0 | 165.0 | 151 |
