# Yöntem v3 — hedefin "hız avantajını" kopyalama denemesi

Tarih: 24 Kasım 2026. Tüm sonuçlar **paper (sanal)** işlemdir; gerçek emir gönderilmedi, API anahtarı kullanılmadı.

## 1. Neden bu yöntem?

`performance_gap.md` şunu gösterdi: hedef cüzdanın kârı büyük olasılıkla fiyatı **yaklaşık 1 saniye önce** doğru
tahmin etmesinden geliyor (hipotez). Bizim botumuz adil fiyatı Binance spot işlemlerinden **saniyede bir** hesaplıyordu;
geçmiş veriyle yapılan testte "1 sn daha erken davranabilsek" senaryosu zarardan kâra geçiyordu.

## 2. Ne eklendi? (`live_paper.py`)

1. **Hızlı sinyal:** Binance vadeli (futures) en iyi alış/satış akışı — milisaniye düzeyinde, saniyede ~800 güncelleme.
   Bu fiyat, spot ölçeğine yavaş bir fark düzeltmesiyle (60 sn ortalama) taşınıp adil olasılık her 0,1 sn'de yeniden hesaplanıyor.
   Vadeli erişilemezse otomatik olarak Binance spot en iyi alış/satış akışına geçiyor.
2. **Hızlı iptal ("fade"):** bekleyen alış teklifinin adil değeri 1 sent aleyhe dönünce teklif 0,2 sn içinde iptal ediliyor.
3. **Daha gerçekçi test modeli:** eski model iptalleri *anında* sayıyordu (iyimser). Artık iptal/değiştirme de gecikmeli;
   iptal yolu sırasında gelen dolumlar "maker_late" olarak sayılıyor. Aynı işlem hacmi iki teklifi birden dolduramıyor.
4. **Pencere zamanlaması:** hedefin son 60 sn'deki pasif işlemleri zarardı → v3'te pencerenin son %20'sinde pasif teklif yok.
5. **Ölçüm aracı (`tools/lead_lag.py`):** vadeli fiyat, spot fiyat ve Polymarket fiyatı arasında kimin önde olduğunu ölçüyor.

## 3. Canlı paper test sonucu (24 Kasım 17:27–18:49 UTC, 38 market)

Aynı canlı veri akışında 7 varyant yan yana çalıştı (BTC 5 dk, ETH 5 dk, BTC 15 dk; "BTC" varyantları 22 market).

| Varyant | Ne yapıyor | Hızlı sinyal | Kâr/zarar | Alımlara göre | Kazanma | Dolum (pasif / aktif) |
|---|---|---|---:|---:|---:|---:|
| base | eski yöntem (v1), 1 sn gecikme | yok | +$120,70 | +%2,39 | %52,6 | 622 / 293 |
| btc_taker05_fast | eski en iyi: sadece aktif alım, BTC | yok | +$420,13 | +%19,61 | %54,5 | 0 / 303 |
| **v3_taker_fast** | aynı + hızlı sinyal | **var** | **+$775,21** | +%33,95 | %68,2 | 0 / 329 |
| **v3_mm_fast** | v1 + hızlı sinyal + son %20'de pasif yok | **var** | **+$858,68** | +%15,74 | %64,9 | 141 / 723 |
| v3_mm_fade | v3_mm_fast + hızlı iptal | var | +$805,85 | +%15,31 | %64,9 | 103 / 720 |
| v3_mm_fade_tight | v3_mm_fade, teklif adil değerin 3 sent altı | var | +$786,36 | +%12,97 | %62,2 | 253 / 712 |
| v3_maker_only_fade | sadece pasif teklif + hızlı iptal | var | −$115,30 | −%12,27 | %50,0 | 148 / 0 |

**Eşleştirilmiş karşılaştırma (aynı marketler, tek fark tek ayar):**

| Karşılaştırma | Market | Toplam fark | Market başına | t-değeri* |
|---|---:|---:|---:|---:|
| hızlı sinyal etkisi: v3_taker_fast − btc_taker05_fast | 22 | +$355,08 | +$16,14 | 1,70 |
| v3 toplam etkisi: v3_mm_fast − base | 38 | +$737,97 | +$19,42 | 2,07 |
| hızlı iptal etkisi: v3_mm_fade − v3_mm_fast | 38 | −$52,83 | −$1,39 | −1,82 |

\* Kabaca: 2'nin üstü "tesadüf olma ihtimali düşük" demek; ama tek bir 80 dakikalık oturum ve aynı saatteki marketler
birbirine bağlı olduğu için bu değerler gerçek güvenilirliği **olduğundan yüksek** gösterir.

**Ne öğrendik:**
- Hızlı sinyal her iki karşılaştırmada da kârı artırdı (BTC 5 dk'da en belirgin: +$603 vs +$273).
- Hızlı iptal (fade) **işe yaramadı** — hafif zarar ettirdi. Sadece pasif teklif veren varyant zarar etti.
  Yani kâr, hedefteki gibi pasif tekliflerden değil, **hızlı aktif alımlardan** geliyor. Bu, hedefin tarzından farklı.

## 4. Kim önde? (lead-lag ölçümü, aynı oturumun kaydı)

| Seri | Vadeli fiyattan ne kadar geride | Not |
|---|---:|---|
| Polymarket BTC 15 dk fiyatı | ~0,50 sn | 6 market |
| Polymarket BTC 5 dk fiyatı | ~0,75 sn | 15 market |
| Polymarket ETH 5 dk fiyatı | ~0,25 sn | 15 market |
| Botun kullandığı spot fiyat (saniyelik) | ~0,75 sn | kısmen kayıt biçiminden |

Vadeli fiyat 0,5 sn içinde ≥2 baz puan sıçradığında Polymarket fiyatının aynı yöne ortalama hareketi (sent):

| Market | Olay | +0,25 sn | +0,5 sn | +1 sn | +2 sn | +5 sn | +10 sn |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC 15 dk | 213 | 0,40 | 1,39 | 2,95 | 3,68 | 4,29 | 4,31 |
| BTC 5 dk | 171 | 0,21 | 1,01 | 2,64 | 4,73 | 6,22 | 6,50 |
| ETH 5 dk | 226 | 0,85 | 2,38 | 3,89 | 4,70 | 5,10 | 5,79 |

Yorum: Polymarket fiyatı vadeli piyasadaki hareketi **0,25–1 sn geriden** ve birkaç saniyeye yayılarak izliyor.
Bu, "hedef ~1 sn önde" hipoteziyle uyumlu ve v3'ün neden daha iyi sonuç verdiğini açıklıyor. 10 sn aralıklı tahmin
kalitesinde (log-loss) fark çok küçük (hızlı 0,5218, spot 0,5229, piyasa 0,5199): avantaj saniyenin altında.

## 5. Bu sonuçlara neden temkinli bakmalı?

1. **Paper dolumları büyük olasılıkla fazla iyimser.** Aktif alımlarda, 0,3 sn sonra defterde gördüğümüz eski fiyatlı
   teklifleri aldığımızı varsayıyoruz. Gerçekte aynı fırsatı gören daha hızlı botlar o teklifleri bizden önce alır.
   v3_taker_fast'in +%34'lük getirisi hedefin gerçek +%1,7'sinin ~20 katı — bu tek başına "fazla iyi" uyarısı.
2. **Tek oturum, 80 dakika, 22–38 market.** Bir yönlü fiyat hareketi tüm varyantları aynı anda etkileyebilir.
3. **Gerçek gecikme bilinmiyor.** 0,3 sn emir gecikmesi varsayımı; gerçek emirler imzalanıp Polymarket'e gidiyor ve bu
   makineden/GitHub sunucusundan gerçek süre ölçülmedi.
4. GitHub sunucuları ABD'de; Binance vadeli orada büyük olasılıkla engelli → bot otomatik olarak Binance spot hızlı akışına
   geçer (GitHub kaydındaki "fast feed" satırı hangisinin kullanıldığını gösterir). Sonuçlar bu yüzden farklı çıkabilir.

## 6. GitHub testi

- 17:27 UTC'deki ilk deneme çalıştı ama testlerdeki sabit bir klasör yolu yüzünden düştü; düzeltildi.
- 17:29 UTC'de başlayan çalıştırma (#45449061019) sorunsuz devam ediyor: 7 varyant, 320 dk, bitiş ~23:10 UTC.
  Sonuçlar bitince `paper-results` dalına (SUMMARY.md) ve iş akışı çıktısına (artifact) yazılır.
- **Önemli:** "6 saatte bir otomatik çalış" ayarı GitHub'da yalnızca varsayılan dalda (main) çalışır. İş akışı şu an sadece
  `paper-test-v2` dalında. Düzenli test için PR #1'in main'e birleştirilmesi gerekir (bu karar depo sahibinde).

## 7. Öneri

- **API anahtarını henüz girmeyin.** Gerçek parayla canlı emir kodu yazılmadı ve paper sonuçları iyimser olabilir.
- Önce GitHub'daki 5,3 saatlik test ve en az 3–5 tekrar (birkaç yüz market) aynı yönü göstermeli.
- Bu tutarsa bir sonraki adım: çok küçük tutarla (ör. market başına $5–10) gerçek emir gecikmesini ve dolum oranını ölçen
  kısa bir canlı test — ayrı bir onayla.
- Hızlı iptal (fade) ve sadece pasif teklif varyantları bu testte işe yaramadı; elenmeye aday.
