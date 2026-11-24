# Neden hedefin performansını yakalayamıyoruz? — ölçüm raporu

Oluşturma: 2026-11-24 16:23:26 UTC. Gerçek emir yok. Rakamlar paylaşım (share) başına **sent** cinsindendir (1 sent = $0,01); pozitif = bizim lehimize.

## 1. Piyasa kuralları değişti (Gamma API)

| market | sonuçlanma kuralı | taker ücret eğrisi | fiyat adımı |
|---|---|---|---|
| btc-updown-5m-1774354200 | pencere sonu tek fiyat | 0.25 × (p(1−p))^2, maker rebate %20 | 0.01 |
| btc-updown-15m-1774353600 | pencere sonu tek fiyat | 0.25 × (p(1−p))^2, maker rebate %20 | 0.001 |
| btc-updown-5m-1795532100 | son 60 sn ortalaması (TWAP) | 0.05 × (p(1−p))^1, maker rebate %20 | 0.001 |
| eth-updown-5m-1795532100 | son 60 sn ortalaması (TWAP) | 0.01 × (p(1−p))^1, maker rebate %20 | 0.001 |

Hedefin taker işlemlerinde ödediği ortalama ücret: Mart eğrisiyle **+1,08 sent/share**, aynı işlemler bugünkü eğriyle **+0,86 sent/share** olurdu.

## 2. İşlem kalitesi: hedef (Mart 2026) vs bizim bot (24 Kasım 2026 canlı paper)

Aynı adil değer modeliyle ölçüldü. *İşlem anı*: adil değer − fiyat. *30 sn sonra*: 30 sn sonraki adil değer − fiyat. *Sonuç*: market sonucu (0/1) − fiyat (ücret hariç). *30 sn kayma*: 30 sn sonra − işlem anı (eksi = işlemden sonra fiyat aleyhimize döndü, yani ters seçim).

| kim | rol | fill | share | ort. fiyat | işlem anı | 30 sn sonra | 30 sn kayma | sonuç (ücret hariç) | ücret |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hedef | maker | 468,690 | 8,347,552 | 0.394 | +0,78 | +0,81 | +0,03 | +0,57 | +0,00 |
| hedef | taker | 118,081 | 5,354,564 | 0.380 | +1,53 | +2,07 | +0,54 | +0,88 | +1,08 |
| bizim bot | maker | 185 | 2,067 | 0.404 | +3,33 | +4,87 | +1,54 | -5,27 | +0,00 |
| bizim bot | taker | 1,101 | 22,655 | 0.506 | +6,84 | +2,32 | -4,52 | +2,83 | +0,71 |

### Kategoriye göre (sonuç − fiyat, sent/share, ücret hariç)

| kim | kategori | rol | fill | işlem anı | 30 sn sonra | sonuç |
|---|---|---|---:|---:|---:|---:|
| hedef | BTC 15m | maker | 118,085 | +0,59 | +0,75 | +0,60 |
| hedef | BTC 15m | taker | 29,405 | +1,27 | +1,62 | +0,95 |
| hedef | BTC 5m | maker | 280,354 | +0,96 | +0,83 | +0,51 |
| hedef | BTC 5m | taker | 68,029 | +1,80 | +2,52 | +0,95 |
| hedef | ETH 15m | maker | 70,251 | +0,55 | +0,86 | +0,67 |
| hedef | ETH 15m | taker | 20,647 | +1,29 | +1,75 | +0,55 |
| bizim bot | BTC 15m | maker | 7 | +3,86 | +6,31 | +33,41 |
| bizim bot | BTC 15m | taker | 171 | +9,08 | +2,17 | +17,91 |
| bizim bot | BTC 5m | maker | 145 | +4,21 | +6,59 | -5,23 |
| bizim bot | BTC 5m | taker | 623 | +7,82 | +3,72 | +0,04 |
| bizim bot | ETH 5m | maker | 33 | -4,00 | -9,56 | -24,49 |
| bizim bot | ETH 5m | taker | 307 | +2,95 | -0,96 | -0,69 |

### Hedefin işlemleri: pencerenin neresinde? (sent/share, ücret hariç)

| rol | kalan süre | fill | işlem anı | 30 sn sonra | sonuç |
|---|---|---:|---:|---:|---:|
| maker | son 30 sn | 5,028 | +2,47 | +0,05 | -0,49 |
| maker | 30–60 sn | 11,052 | +0,63 | +0,08 | -1,42 |
| maker | 1–2 dk | 50,217 | +0,86 | +0,78 | -0,00 |
| maker | 2–5 dk | 263,222 | +0,83 | +0,82 | +0,59 |
| maker | 5–15 dk | 139,171 | +0,63 | +0,87 | +0,85 |
| taker | son 30 sn | 1,267 | +4,66 | -0,45 | -1,14 |
| taker | 30–60 sn | 2,604 | +2,86 | +3,92 | +2,10 |
| taker | 1–2 dk | 12,578 | +1,94 | +3,10 | +1,92 |
| taker | 2–5 dk | 65,525 | +1,45 | +2,14 | +0,68 |
| taker | 5–15 dk | 36,107 | +1,39 | +1,69 | +0,87 |

## 3. Hız tavanı: "kuyrukta hep ilk sıradayız ve anında işlem yapıyoruz" (backtest, 2686 market, 2026-11-20 15:55:00 UTC → 2026-11-24 03:55:00 UTC; son 1075 market = test)

| strateji | senaryo | tüm dönem PnL | alımlara göre | test PnL | maker / taker fill | rebate |
|---|---|---:|---:|---:|---:|---:|
| v1 maker+taker (canlı testteki) | bugünkü varsayım (kuyruk sonu, 1 sn) | −$5.202 | -3,17% | −$3.807 | 28,246 / 16,629 | $0 |
| v1 maker+taker (canlı testteki) | kuyrukta ilk sıra, 1 sn | −$4.233 | -2,19% | −$3.638 | 39,061 / 14,618 | $0 |
| v1 maker+taker (canlı testteki) | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | −$3.545 | -1,91% | −$2.944 | 39,602 / 10,719 | $0 |
| v1 maker+taker (canlı testteki) | ilk sıra + en hızlı + %20 maker rebate | −$2.977 | -1,60% | −$2.706 | 39,602 / 10,719 | $568 |
| v1 maker+taker (canlı testteki) | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | +$8.415 | +5,40% | +$2.572 | 29,506 / 11,496 | $455 |
| sadece taker BTC (v2) | bugünkü varsayım (kuyruk sonu, 1 sn) | +$936 | +2,39% | −$519 | 0 / 13,493 | $0 |
| sadece taker BTC (v2) | kuyrukta ilk sıra, 1 sn | +$936 | +2,39% | −$519 | 0 / 13,493 | $0 |
| sadece taker BTC (v2) | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | +$825 | +2,62% | −$219 | 0 / 10,707 | $0 |
| sadece taker BTC (v2) | ilk sıra + en hızlı + %20 maker rebate | +$825 | +2,62% | −$219 | 0 / 10,707 | $0 |
| sadece taker BTC (v2) | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | +$2.170 | +6,54% | +$411 | 0 / 11,234 | $0 |
| sadece maker, fiyat farkı 0.01 | bugünkü varsayım (kuyruk sonu, 1 sn) | −$21.319 | -5,49% | −$9.793 | 99,283 / 0 | $0 |
| sadece maker, fiyat farkı 0.01 | kuyrukta ilk sıra, 1 sn | −$16.211 | -3,45% | −$7.601 | 124,094 / 0 | $0 |
| sadece maker, fiyat farkı 0.01 | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | −$16.211 | -3,45% | −$7.601 | 124,094 / 0 | $0 |
| sadece maker, fiyat farkı 0.01 | ilk sıra + en hızlı + %20 maker rebate | −$14.512 | -3,09% | −$6.916 | 124,094 / 0 | $1,699 |
| sadece maker, fiyat farkı 0.01 | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | −$1.294 | -0,30% | −$1.196 | 112,621 / 0 | $1,597 |
| sadece maker, fiyat farkı 0.02 | bugünkü varsayım (kuyruk sonu, 1 sn) | −$17.201 | -5,14% | −$7.805 | 85,666 / 0 | $0 |
| sadece maker, fiyat farkı 0.02 | kuyrukta ilk sıra, 1 sn | −$12.559 | -3,05% | −$5.891 | 109,368 / 0 | $0 |
| sadece maker, fiyat farkı 0.02 | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | −$12.559 | -3,05% | −$5.891 | 109,368 / 0 | $0 |
| sadece maker, fiyat farkı 0.02 | ilk sıra + en hızlı + %20 maker rebate | −$11.074 | -2,69% | −$5.289 | 109,368 / 0 | $1,485 |
| sadece maker, fiyat farkı 0.02 | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | +$1.741 | +0,47% | +$287 | 94,680 / 0 | $1,337 |
| sadece maker, fiyat farkı 0.03 | bugünkü varsayım (kuyruk sonu, 1 sn) | −$15.508 | -5,49% | −$7.623 | 71,972 / 0 | $0 |
| sadece maker, fiyat farkı 0.03 | kuyrukta ilk sıra, 1 sn | −$10.273 | -2,93% | −$5.011 | 93,347 / 0 | $0 |
| sadece maker, fiyat farkı 0.03 | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | −$10.273 | -2,93% | −$5.011 | 93,347 / 0 | $0 |
| sadece maker, fiyat farkı 0.03 | ilk sıra + en hızlı + %20 maker rebate | −$9.015 | -2,57% | −$4.489 | 93,347 / 0 | $1,258 |
| sadece maker, fiyat farkı 0.03 | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | +$3.665 | +1,23% | +$920 | 76,206 / 0 | $1,072 |
| sadece maker, fiyat farkı 0.05 | bugünkü varsayım (kuyruk sonu, 1 sn) | −$9.309 | -4,80% | −$4.780 | 49,407 / 0 | $0 |
| sadece maker, fiyat farkı 0.05 | kuyrukta ilk sıra, 1 sn | −$7.981 | -3,35% | −$4.176 | 63,901 / 0 | $0 |
| sadece maker, fiyat farkı 0.05 | ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn) | −$7.981 | -3,35% | −$4.176 | 63,901 / 0 | $0 |
| sadece maker, fiyat farkı 0.05 | ilk sıra + en hızlı + %20 maker rebate | −$7.144 | -2,99% | −$3.819 | 63,901 / 0 | $838 |
| sadece maker, fiyat farkı 0.05 | ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser) | +$5.470 | +2,90% | +$1.642 | 47,751 / 0 | $652 |

## 4. Yorum

- **Hedefin kârının kaynağı:** 17–24 Mart BTC/ETH işlemlerinde maker tarafı +$47.227 (share başına +0,57 sent; işlemden 30 sn sonraki kayma +0,03 sent, yani ters seçim yok), taker tarafı ücret sonrası −$10.656. Toplam +$36.571 (maker rebate hariç).
- **Son dakika değil, pencerenin başı/ortası:** hedefin son 60 sn'deki maker işlemleri zarar ettirmiş (son 30 sn: -0,49, 30–60 sn: -1,42 sent/share); kâr 2–15 dk kala verilen tekliflerden. Yani yeni TWAP kuralı tek başına açıklama değil.
- **Ücret engel değil:** hedefin taker ücreti Mart eğrisiyle +1,08 sent/share idi; bugünkü eğriyle +0,86 olurdu (daha ucuz).
- **Bizim sinyalimiz daha gürültülü/geç:** bizim taker işlemlerimizde model işlem anında +6,84 sent avantaj görüyor ama bu 30 sn içinde -4,52 sent değişiyor; hedefin taker işlemlerinde aynı ölçü +0,54 sent (fiyat hedefin lehine gitmeye devam etmiş). Hedef fiyat hareketini bizden önce görüp işlem yapıyordu (hipotez).
- **Her şey ~1 saniyeye bağlı (backtest, Kasım verisi):** canlı testteki strateji kuyrukta hep ilk sırada, en hızlı tepkiyle ve %20 rebate ile bile tüm dönemde −$2.977 (-1,60%); aynı şey 1 sn daha erken davranabilseydik +$8.415 (+5,40%, test +$2.572). Geçmiş veri bu 1 saniyeyi güvenilir ayırt edemiyor; bunu ancak gerçek emir gösterir.
- **Sadece maker (hedefin yaptığı) bugün muhafazakâr varsayımla zarar:** en iyi fiyat farkıyla bile −$7.144 (sadece maker, fiyat farkı 0.05).
- **Bizim canlı maker örneğimiz çok küçük** (185 fill); sonucu (-5,27 sent/share) şans payı çok yüksek, karar için yeterli değil.

## Varsayımlar ve sınırlar
- Hedefin Data API zaman damgaları 2 sn geri kaydırıldı (ölçülen medyan gecikme 2,2 sn). Mart marketleri tek fiyatla sonuçlandığı için adil değer TWAP'sız hesaplandı; Binance fiyatı Chainlink'in yerine kullanıldı.
- Hedefin maker rebate gelirleri işlem verisinde görünmez; yukarıdaki hedef rakamları rebate hariçtir.
- Hız tavanı bir üst sınırdır: geçmiş işlemlerin bizim emrimiz olsaydı da aynen gerçekleşeceği varsayılır.
- Bizim canlı örneğimiz küçük (birkaç yüz fill); hedefinki yüz binlerce fill.
