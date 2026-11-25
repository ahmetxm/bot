# Emir gecikmesi / dolum testi — probe

Başlangıç 2026-11-24 23:05:20 UTC, bitiş 2026-11-24 23:07:35 UTC. Konum: US-CA (Polymarket emir engeli: **True**). Saat farkı kaynağı: https://data-api.binance.vision/api/v3/time (-0.3 ms).

Bu ölçümde **emir gönderilmedi** (anahtarsız mod). Gerçek emir gecikmesi ve dolum oranı `--live` ile ölçülür.

| ölçüm | medyan | p90 | maks | n |
|---|---|---|---|---|
| CLOB GET /time gidiş-dönüş | 153.8 ms | 157.4 ms | 161.6 ms | 20 |
| CLOB GET /book gidiş-dönüş | 159.7 ms | 173.5 ms | 194.2 ms | 20 |
| emir hazırlama + imza (yerel) | 4.3 ms | 4.4 ms | 4.4 ms | 19 |
| Polymarket WS veri gecikmesi | 78.5 ms | 889.9 ms | 3571.8 ms | 100469 |
| Binance vadeli WS veri gecikmesi | 55.3 ms | 74.7 ms | 105.8 ms | 16027 |

- İlk bağlantı (TLS) maliyeti: 183.6 ms; bir markette ilk emir imzası 333.7 ms (market bilgisi indiriliyor → market açılınca önceden ısıtılmalı).
- Tahmini 'karar → emir borsada' süresi (WS gecikmesi + imza + yarım gidiş-dönüş): **162.7 ms**. Bu bir tahmindir; borsanın emir işleme süresi dahil değildir.
- Not: WS gecikmesi iki saat arasındaki farka dayanır (Binance saati referans); saat ölçümünün gidiş-dönüşü 108.0 ms olduğundan hata payı en fazla ±54 ms'dir. Yüksek p90/maks değerleri büyük olasılıkla kısa yoğunluk (mesaj yığılması) anlarından gelir.
