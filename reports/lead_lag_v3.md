# Lead-lag: Binance futures (fast feed) vs Binance spot vs Polymarket Up mid

Recordings: feed_v3_20261124_172704.jsonl.gz. Grid 0.1 s. Positive lag = the second series moves AFTER the futures mid.

| series | peak lag (s) | corr at peak | corr at lag 0 | n |
|---|---:|---:|---:|---:|
| BTC 15m | +0.50 | 0.375 | 0.170 | 6 |
| BTC 5m | +0.75 | 0.304 | 0.092 | 15 |
| ETH 5m | +0.25 | 0.387 | 0.272 | 15 |
| ETH spot vs futures | +0.75 | 0.518 | 0.306 |  |
| BTC spot vs futures | +0.75 | 0.618 | 0.327 |  |

Event study (futures move >= 2 bp within 0.5 s): average Polymarket Up-mid move in the same direction, cents, h seconds after the move:

| category | events | +0.25s | +0.5s | +1.0s | +2.0s | +3.0s | +5.0s | +10.0s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC 15m | 213 | 0.40 | 1.39 | 2.95 | 3.68 | 3.95 | 4.29 | 4.31 |
| BTC 5m | 171 | 0.21 | 1.01 | 2.64 | 4.73 | 5.36 | 6.22 | 6.50 |
| ETH 5m | 226 | 0.85 | 2.38 | 3.89 | 4.70 | 4.67 | 5.10 | 5.79 |
