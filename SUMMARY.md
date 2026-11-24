# Paper test - kümülatif özet

Gerçek emir YOK; tüm işlemler canlı Polymarket verisi üzerinde simüle edilir. Her çalıştırma ~5,5 saat sürer (GitHub Actions).

Toplam çalıştırma: 1

## Varyantlar (tüm çalıştırmalar toplamı)

| varyant | çalıştırma | işlem yapılan market | toplam PnL | PnL / alım | kazanma | alım | maker / taker | ücret | en kötü çalıştırma |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v3_taker_fast | 1 | 82 | $+1,986.94 | +18.06% | 72.0% | $11,002 | 0 / 1318 | $291.08 | $+0.00 |
| v3_mm_fade | 1 | 149 | $+1,382.64 | +5.86% | 59.1% | $23,582 | 442 / 2676 | $409.81 | $+0.00 |
| v3_mm_fast | 1 | 149 | $+1,362.09 | +5.58% | 59.1% | $24,417 | 601 / 2677 | $408.48 | $+0.00 |
| v3_mm_fade_tight | 1 | 149 | $+1,361.95 | +5.28% | 57.7% | $25,814 | 1002 / 2609 | $393.55 | $+0.00 |
| btc_taker05_fast | 1 | 82 | $+1,094.29 | +9.98% | 59.8% | $10,960 | 0 / 1336 | $303.12 | $+0.00 |
| base | 1 | 84 | $-329.82 | -2.75% | 52.4% | $11,978 | 1131 / 712 | $86.06 | $-329.82 |
| v3_maker_only_fade | 1 | 130 | $-350.24 | -4.65% | 57.7% | $7,531 | 1024 / 0 | $0.00 | $-350.24 |

Hedef cüzdan referansı: PnL / alım +%1,71, kazanma %50,6.

## Varyant x kategori

| varyant | kategori | market | PnL | PnL / alım | kazanma |
|---|---|---:|---:|---:|---:|
| base | BTC 15m | 12 | $-43.21 | -2.32% | 50.0% |
| base | BTC 5m | 36 | $-143.26 | -2.66% | 52.8% |
| base | ETH 5m | 36 | $-143.35 | -3.03% | 52.8% |
| btc_taker05_fast | BTC 15m | 20 | $+541.45 | +21.78% | 80.0% |
| btc_taker05_fast | BTC 5m | 62 | $+552.84 | +6.52% | 53.2% |
| v3_maker_only_fade | BTC 15m | 18 | $+11.30 | +1.03% | 66.7% |
| v3_maker_only_fade | BTC 5m | 63 | $-60.71 | -1.32% | 55.6% |
| v3_maker_only_fade | ETH 5m | 49 | $-300.83 | -16.53% | 57.1% |
| v3_mm_fade | BTC 15m | 21 | $+610.08 | +19.77% | 71.4% |
| v3_mm_fade | BTC 5m | 64 | $+1,432.22 | +12.13% | 67.2% |
| v3_mm_fade | ETH 5m | 64 | $-659.66 | -7.59% | 46.9% |
| v3_mm_fade_tight | BTC 15m | 21 | $+676.35 | +21.32% | 71.4% |
| v3_mm_fade_tight | BTC 5m | 64 | $+1,464.73 | +10.81% | 65.6% |
| v3_mm_fade_tight | ETH 5m | 64 | $-779.12 | -8.57% | 45.3% |
| v3_mm_fast | BTC 15m | 21 | $+593.14 | +18.94% | 71.4% |
| v3_mm_fast | BTC 5m | 64 | $+1,472.03 | +11.91% | 67.2% |
| v3_mm_fast | ETH 5m | 64 | $-703.08 | -7.87% | 46.9% |
| v3_taker_fast | BTC 15m | 19 | $+615.68 | +24.43% | 78.9% |
| v3_taker_fast | BTC 5m | 63 | $+1,371.26 | +16.17% | 69.8% |

## Çalıştırma bazında PnL

| çalıştırma | base | btc_taker05_fast | v3_maker_only_fade | v3_mm_fade | v3_mm_fade_tight | v3_mm_fast | v3_taker_fast |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20261124_2304_45449061019 | $-329.82 | $+1,094.29 | $-350.24 | $+1,382.64 | $+1,361.95 | $+1,362.09 | $+1,986.94 |
