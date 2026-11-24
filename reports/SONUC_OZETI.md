# Sonuç özeti — strateji kopyası botu (paper trading)

Tarih: 2026-11-24. Hedef cüzdan: `0xd0d6053c3c37e727402d84c14069780d360993aa` (k9Q2mX4L8A7ZP3R).
Gerçek emir gönderilmedi; tüm sonuçlar paper (sanal) işlemlerdir. Başlangıç bakiyesi $10.000, market başına en fazla $400.

## Güncelleme — 24 Kasım 2026, 15:40 UTC

**Muhafazakâr yeniden kalibrasyon (3 sn gecikme, ileriye bakma yok, `strategy_backtest_v2_fixed3.md`):**
- Maker (pasif emir) içeren tüm kombinasyonlar zararda ya da sıfıra yakın → maker tarafı sistematik olarak zararlı.
- En iyi seçenek: sadece taker, sadece BTC (5m + 15m), edge 5 sent. Train: **+$1.736** (alımlara göre %7,8).
  Test (görülmemiş dönem): **−$360** (−%2,3). Kategori: BTC 5m +$164, BTC 15m −$261.
- Yani train performansı test dönemine taşınmıyor; "train'i yakalamak" şu an mümkün görünmüyor.

**Canlı paper testler (çalışıyor, ara sonuç — sadece çözülmüş marketler):**

| Test | Süre (şu ana kadar) | PnL | Fill |
|---|---:|---:|---:|
| v1 base (BTC 5m, ETH 5m, BTC 15m; maker + taker) | 52 dk | +$33,83 | 151 |
| v1 sadece BTC | 52 dk | +$125,11 | 89 |
| v1 sadece BTC, sadece taker | 52 dk | −$53,10 | 50 |
| v2 base | 25 dk | +$29,53 | 47 |
| v2 BTC taker 5¢ (1 sn gecikme) | 25 dk | −$12,84 | 7 |
| v2 BTC taker 5¢ hızlı (0,3 sn) | 25 dk | +$40,17 | 37 |
| v2 BTC taker 8¢ hızlı | 25 dk | −$13,07 | 7 |
| v2 sadece BTC 5m taker hızlı | 25 dk | +$42,33 | 36 |
| v2 sadece BTC 15m taker hızlı | 25 dk | −$2,17 | 1 |
| v2 BTC geniş maker + koruma | 25 dk | −$2,84 | 8 |

Örnekler çok küçük (her biri birkaç düzine market); bu rakamlar istatistiksel olarak anlamlı değil.

**GitHub (ahmetxm/bot):** ilk sürüm `main`'de, yeni sürüm `paper-test-v2` dalında (PR #1, birleştirilmedi). Kesintisiz test için
GitHub Actions iş akışı hazır, ancak bağlı GitHub uygulamasının workflow dosyası yazma izni olmadığından
`.github/workflows/paper.yml` dosyasını depo sahibinin eklemesi gerekiyor (içerik: `ci/paper-test.yml`).
Eklendiğinde her çalıştırma ~5,5 saat sürer, sonuçlar `paper-results` dalındaki `SUMMARY.md`'ye eklenir.

**Öneri değişmedi: Şu an API anahtarı girmeyin.**

## 1. Hedef cüzdan ne yapıyordu?
- Kripto Up/Down marketleri (BTC/ETH, 5 dk ve 15 dk) üzerinde **market-making**: fill'lerin %78'i maker,
  marketlerin %94'ünde hem Up hem Down alınıyor, Up+Down medyan maliyeti 0,918.
- Mart 2026'daki 7 günde: alımlara göre kâr %1,71, kazanma oranı %50,6. Cüzdan 244 gündür pasif.

## 2. Bot ne yapıyor?
Hedefin işlemlerini kopyalamıyor; aynı mantığı kendi başına uyguluyor: Binance + Chainlink fiyatından "Up" olasılığını
hesaplıyor, iki tarafa da bu değerin altından alış emri koyuyor, fiyat çok ucuz kalırsa taker olarak alıyor,
pozisyonu çözüme kadar tutuyor. Risk limitleri: market başına özsermayenin %10'u, günlük $500 zarar durdurma, %5 stop-loss uyarısı.

## 3. Backtest (3.052 çözülmüş market, 20–24 Kasım 2026)
Parametreler ilk %60'lık dönemde seçildi, son %40'ta (1.221 market) dışarıdan test edildi.

| Gecikme varsayımı (test dönemi) | Seçilen parametreler | Sadece maker |
|---|---:|---:|
| Ölçülen rastgele gecikme | +$5.175 (alımlara göre %5,5) | +$2.320 |
| Sabit 2 sn | +$1.243 | −$97 |
| Sabit 3 sn (ileriye bakma yok) | −$1.646 | −$1.513 |
| Sabit 3 sn + 2 sn emir gecikmesi | −$1.624 | −$1.601 |

Yorum: Sonuç tamamen işlem zaman damgalarının gecikme varsayımına bağlı. İleriye bakma (look-ahead) etkisi
kaldırıldığında zarar ediyor. **Backtest kesin bir sonuç vermiyor.**

## 4. Canlı paper test (80 dakika, 24 Kasım 04:53–06:20 UTC, gerçek order book + gerçek fiyatlar)

| Çalıştırma | Market | PnL | Kazanma oranı | Alım | PnL / alım | Maker / taker fill | Ücret |
|---|---:|---:|---:|---:|---:|---:|---:|
| Strateji kopyası (seçilen parametreler) | 40 (37 işlemli) | **−$79,70** | %45,9 | $2.711 | −%2,94 | 86 / 320 | $34,64 |
| Sadece maker (half_spread 0,08) | 40 (14 işlemli) | **−$84,40** | %35,7 | $160 | −%52,7 | 42 / 0 | $0 |

Kategoriye göre (strateji kopyası): BTC 5m −$25,60 · ETH 5m −$178,45 · BTC 15m +$124,34.
Adil değer modeli canlıda market fiyatından çok az daha isabetliydi (log-loss 0,355 vs 0,359), ama bu fark
ücretleri ve ters seçimi (adverse selection) karşılamaya yetmedi.

## 5. Karar
- Hedefin performansına (alımlara göre +%1,71) ulaşılamadı: canlı paper testte −%2,94.
- 40 market küçük bir örnek; sonuç istatistiksel olarak kesin değil, ama kâr kanıtı da yok.
- **Öneri: Şu an API anahtarı girmeyin.** Önce botu en az 1–2 gün kesintisiz paper modda çalıştırıp
  sonucun pozitif olup olmadığını görmek gerekir.
- Strateji kopyası için gerçek emir gönderme kodu henüz yazılmadı ve test edilmedi; live mod kilitli.

## Varsayımlar
- Maker emirlerimiz aynı fiyattaki mevcut emirlerin arkasında kuyruğa giriyor (muhafazakâr).
- Kararla emir arasında 1 sn gecikme; taker ücreti = oran × p × (1−p) (BTC: 0,05, ETH: 0,01); maker rebate 0.
- Paper taker alımları gerçek likiditeyi tüketmiyor, ama aynı likiditenin tekrar kullanılması engellendi.
