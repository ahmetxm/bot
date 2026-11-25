# Paper test - kümülatif özet

Gerçek emir YOK; tüm işlemler canlı Polymarket verisi üzerinde simüle edilir. Her çalıştırma ~5,5 saat sürer (GitHub Actions).

Toplam çalıştırma: 2

## Varyantlar (tüm çalıştırmalar toplamı)

| varyant | çalıştırma | işlem yapılan market | toplam PnL | PnL / alım | kazanma | alım | maker / taker | ücret | en kötü çalıştırma |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v3_taker_fast | 2 | 168 | $+3,865.84 | +17.33% | 70.8% | $22,310 | 0 / 2691 | $589.54 | $+0.00 |
| v3_mm_fade_tight | 2 | 301 | $+3,524.10 | +6.99% | 60.1% | $50,399 | 1980 / 5115 | $786.75 | $+0.00 |
| v3_mm_fade | 2 | 299 | $+3,324.54 | +7.29% | 60.9% | $45,609 | 818 / 5255 | $814.52 | $+0.00 |
| v3_mm_fast | 2 | 299 | $+3,269.38 | +6.95% | 60.5% | $47,021 | 1094 / 5260 | $813.60 | $+0.00 |
| btc_taker05_fast | 2 | 168 | $+2,830.42 | +12.56% | 63.1% | $22,529 | 0 / 2738 | $609.18 | $+0.00 |
| v3_maker_only_fade | 2 | 249 | $+194.97 | +1.37% | 61.0% | $14,238 | 1851 / 0 | $0.00 | $-350.24 |
| base | 2 | 236 | $-1,029.62 | -3.22% | 53.4% | $32,006 | 3108 / 2074 | $272.80 | $-699.80 |

Hedef cüzdan referansı: PnL / alım +%1,71, kazanma %50,6.

## Varyant x kategori

| varyant | kategori | market | PnL | PnL / alım | kazanma |
|---|---|---:|---:|---:|---:|
| base | BTC 15m | 34 | $-20.26 | -0.34% | 61.8% |
| base | BTC 5m | 101 | $+124.47 | +0.84% | 52.5% |
| base | ETH 5m | 101 | $-1,133.83 | -10.21% | 51.5% |
| btc_taker05_fast | BTC 15m | 42 | $+895.60 | +14.63% | 73.8% |
| btc_taker05_fast | BTC 5m | 126 | $+1,934.82 | +11.79% | 59.5% |
| v3_maker_only_fade | BTC 15m | 36 | $+63.87 | +2.41% | 69.4% |
| v3_maker_only_fade | BTC 5m | 123 | $+273.08 | +3.14% | 59.3% |
| v3_maker_only_fade | ETH 5m | 90 | $-141.97 | -4.89% | 60.0% |
| v3_mm_fade | BTC 15m | 43 | $+828.36 | +11.65% | 69.8% |
| v3_mm_fade | BTC 5m | 129 | $+3,375.95 | +14.44% | 69.8% |
| v3_mm_fade | ETH 5m | 127 | $-879.77 | -5.82% | 48.8% |
| v3_mm_fade_tight | BTC 15m | 43 | $+946.99 | +12.99% | 69.8% |
| v3_mm_fade_tight | BTC 5m | 129 | $+3,536.70 | +13.02% | 69.0% |
| v3_mm_fade_tight | ETH 5m | 129 | $-959.58 | -6.02% | 48.1% |
| v3_mm_fast | BTC 15m | 43 | $+825.00 | +11.49% | 69.8% |
| v3_mm_fast | BTC 5m | 129 | $+3,382.38 | +13.88% | 68.2% |
| v3_mm_fast | ETH 5m | 127 | $-937.99 | -6.06% | 49.6% |
| v3_taker_fast | BTC 15m | 40 | $+780.42 | +13.45% | 75.0% |
| v3_taker_fast | BTC 5m | 128 | $+3,085.42 | +18.69% | 69.5% |

## Çalıştırma bazında PnL

| çalıştırma | base | btc_taker05_fast | v3_maker_only_fade | v3_mm_fade | v3_mm_fade_tight | v3_mm_fast | v3_taker_fast |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20261125_0434_45478122431 | $-699.80 | $+1,736.13 | $+545.21 | $+1,941.89 | $+2,162.15 | $+1,907.29 | $+1,878.90 |
| 20261124_2304_45449061019 | $-329.82 | $+1,094.29 | $-350.24 | $+1,382.64 | $+1,361.95 | $+1,362.09 | $+1,986.94 |
