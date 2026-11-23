# Backtest report - Polymarket copy-trade bot (paper trading)

Target `0xd0d6053c3c37e727402d84c14069780d360993aa` | window 2026-03-17 13:12:57 UTC -> 2026-03-24 12:12:57 UTC (6.96 days) | 834,276 target fills in 7,875 markets

Starting balance $10,000 | target capital estimate $69,910 | copy ratio 0.1430 | poll 10 s + 2 s latency | slippage 30 bps

| scenario | final equity | PnL | return % | win rate % | orders | fees | Sharpe (hourly, ann.) | max DD % | halted days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| target_replica | $190,163.21 | $120,253.03 | 172.01 | 50.59 | 834,226 | $0.00 | 34.116 | 9.21 | 0 |
| ideal_copy | $38,914.98 | $28,914.98 | 289.15 | 50.17 | 338,148 | $0.00 | 30.953 | 17.49 | 3 |
| realistic_copy | $6,356.34 | $-3,643.66 | -36.44 | 43.31 | 26,049 | $2,450.93 | -19.628 | 38.60 | 8 |
| realistic_taker_only | $8,076.92 | $-1,923.08 | -19.23 | 46.53 | 19,868 | $1,726.74 | -14.039 | 24.77 | 8 |
| diag_fill_price_with_fees | $7,778.54 | $-2,221.46 | -22.21 | 46.54 | 103,945 | $5,742.61 | -6.884 | 29.83 | 8 |
| diag_realistic_no_loss_halt | $1,254.12 | $-8,745.88 | -87.46 | 43.15 | 78,742 | $5,886.60 | -41.407 | 87.93 | 0 |

Polymarket ground truth for the target in this window: trade PnL $140,418, economic PnL $108,090 (fees paid $41,100, maker rebates $8,772).

## Verdict

- Replay check: target PnL replayed from fills $120,253 vs Polymarket trade PnL $140,418 / economic PnL $108,090 in the same window.
- Target return on its deployed capital ($69,910): 172.01% in 6.96 days.
- Ideal copy (instant, same price, no fees): 289.15% (PnL $28,914.98).
- Realistic copy (10 s polling, latency, slippage, taker fees): -36.44% (PnL $-3,643.66, fees $2,450.93).
- The gap between ideal and realistic copy is the edge lost to latency, slippage and fees: the target earns mostly as a MAKER and at sub-second speed, which a 10-second polling follower using taker orders cannot reproduce.
- Copying only the target's taker fills: -19.23% (PnL $-1,923.08).
- Diagnostic - target's own prices but paying taker fees: -22.21% (fees $5,742.61) -> isolates the cost of fees alone.
- Diagnostic - realistic copy WITHOUT the $500 daily-loss halt: -87.46% (PnL $-8,745.88); the halt fired on 8 of 8 days in realistic_copy.
- The target wallet has been inactive for 244.4 days, so a live copy bot started today would receive no trades to copy.

## Risk controls applied (copy scenarios)

- max position per market: 10% of equity
- max daily loss: $500 (new entries halted for the rest of the UTC day)
- stop-loss: warning when a position loses > 5% of equity (action: warn)
- min order: 5.0 shares / $1.0

Files: `performance_report.json`, `backtest_<scenario>_metrics.json|trades.csv.gz|markets.csv|equity.csv`, `charts/backtest_equity.png`.