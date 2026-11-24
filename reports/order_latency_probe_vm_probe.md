# Emir gecikmesi / dolum testi — probe

Başlangıç 2026-11-24 20:01:27 UTC, bitiş 2026-11-24 20:06:42 UTC. Konum: US-OR (Polymarket emir engeli: **True**). Saat farkı kaynağı: https://data-api.binance.vision/api/v3/time (-0.5 ms).

Bu ölçümde **emir gönderilmedi** (anahtarsız mod). Gerçek emir gecikmesi ve dolum oranı `--live` ile ölçülür.

| ölçüm | medyan | p90 | maks | n |
|---|---|---|---|---|
| CLOB GET /time gidiş-dönüş | 157.9 ms | 167.9 ms | 460.4 ms | 20 |
| CLOB GET /book gidiş-dönüş | 155.9 ms | 160.0 ms | 173.7 ms | 20 |
| emir hazırlama + imza (yerel) | 3.8 ms | 3.9 ms | 4.0 ms | 19 |
| Polymarket WS veri gecikmesi | 81.6 ms | 653.9 ms | 6902.8 ms | 179182 |
| Binance vadeli WS veri gecikmesi | 49.7 ms | 52.8 ms | 116.7 ms | 181775 |

- İlk bağlantı (TLS) maliyeti: 200.2 ms; bir markette ilk emir imzası 362.2 ms (market bilgisi indiriliyor → market açılınca önceden ısıtılmalı).
- Tahmini 'karar → emir borsada' süresi (WS gecikmesi + imza + yarım gidiş-dönüş): **163.3 ms**. Bu bir tahmindir; borsanın emir işleme süresi dahil değildir.
- Not: WS gecikmesi iki saat arasındaki farka dayanır (Binance saati referans); saat ölçümünün gidiş-dönüşü 100.0 ms olduğundan hata payı en fazla ±50 ms'dir. Yüksek p90/maks değerleri büyük olasılıkla kısa yoğunluk (mesaj yığılması) anlarından gelir.
