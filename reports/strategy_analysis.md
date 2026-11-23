# Strategy analysis - target wallet

Wallet `0xd0d6053c3c37e727402d84c14069780d360993aa` | data window 2026-03-17 12:12:57 UTC -> 2026-03-24 12:12:57 UTC (7.0 days, 842,080 fills, 7,933 markets)

## Key findings

- Liquidity role: 78.2% of fills / 58.1% of USDC volume are MAKER (passive limit orders) - the wallet is primarily a market maker.
- Market focus: BTC 5m+15m Up/Down = 56.3% of USDC volume; all crypto Up/Down (5m/15m/1h) = 100.0%.
- Activity: 120,297 fills/day across 1,133 markets/day; $1,132,416 USDC/day.
- Sizing: median fill $4.26, mean $9.41; median per-market buy volume $478.
- Two-sided: buys BOTH Up and Down in 93.9% of markets (median combined cost 0.918).
- Results (evaluated markets): win rate 50.6%, PnL $120,025, ROI on buy volume 1.71%.
- Ground truth (Polymarket): all-time economic PnL $1,483,450, volume $90,149,167.
- WARNING: the wallet has been inactive for 244.4 days (last dense activity 2026-03-24 12:12:57 UTC). A live copy bot would currently receive no signals.

## Market focus (USDC share)

| category | fills | USDC | share % |
|---|---:|---:|---:|
| BTC 5m | 348,257 | $2,737,668 | 34.54 |
| BTC 15m | 147,427 | $1,725,573 | 21.77 |
| BTC 1h | 41,375 | $898,654 | 11.34 |
| ETH 15m | 90,858 | $861,076 | 10.86 |
| SOL 5m | 70,980 | $554,458 | 7.00 |
| XRP 5m | 61,707 | $374,360 | 4.72 |
| ETH 1h | 22,818 | $371,182 | 4.68 |
| SOL 15m | 30,995 | $238,788 | 3.01 |
| XRP 15m | 27,663 | $165,156 | 2.08 |

## Performance by category (resolved, non-truncated markets)

| category | markets | PnL | win rate % | ROI % |
|---|---:|---:|---:|---:|
| BTC 5m | 1,885 | $45,208 | 58.1 | 2.04 |
| BTC 15m | 646 | $31,993 | 57.4 | 2.18 |
| SOL 5m | 1,665 | $15,712 | 51.5 | 2.85 |
| ETH 15m | 645 | $14,217 | 46.7 | 1.82 |
| BTC 1h | 154 | $9,926 | 59.1 | 1.13 |
| SOL 15m | 532 | $9,546 | 41.5 | 4.02 |
| ETH 1h | 149 | $494 | 43.0 | 0.14 |
| XRP 15m | 532 | $-1,331 | 37.0 | -0.81 |
| XRP 5m | 1,667 | $-5,741 | 47.1 | -1.54 |

Charts: `charts/activity_and_focus.png`, `charts/pnl_distribution.png`, `charts/timing_and_calibration.png`. Full numbers: `strategy_analysis.json`.