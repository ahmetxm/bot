# Gerçek emir gecikmesi ve dolum oranı testi — kılavuz

Tarih: 24 Kasım 2026. Araç: `tools/order_latency_test.py`.

## Durum

- **Gerçek emirli test henüz yapılmadı.** Bu sunucu ABD'de (Oregon). Polymarket ABD'den gelen emirleri engelliyor
  (kontrol: `{"blocked": true, "country": "US", "region": "OR"}`). GitHub'ın test makineleri de büyük olasılıkla ABD'de.
  Engeli VPN/proxy ile aşmak hem Polymarket kurallarına hem bu platformun kurallarına aykırı; yapılmadı ve yapılmamalı.
- **Anahtarsız ölçüm yapıldı** (emir yok, para yok): sonuçlar `order_latency_probe_vm_probe.md`.
- **Gerçek test aracı hazır ve sahte borsa ile test edildi**, ama gerçek emirle hiç çalıştırılmadı.
  Türkiye Polymarket'in engelli ülke listesinde görünmüyor; araç bunu çalışırken kendisi kontrol eder, engel varsa durur.
- **Önemli bulgu:** botun kullandığı eski kütüphane (`py-clob-client`) Nisan 2026'daki borsa güncellemesinden beri
  emir gönderemiyor. Bot ve test aracı yeni resmi kütüphaneye (`polymarket-client`) geçirildi.

## Anahtarsız ölçüm (bu sunucudan, ABD) — özet

| ölçüm | medyan | not |
|---|---|---|
| Borsaya istek gidiş-dönüş | ~156 ms | ABD → Polymarket sunucusu |
| Emir hazırlama + imza | ~3,8 ms | ilk emirde ~362 ms (önceden ısıtılmalı) |
| Polymarket fiyat akışı gecikmesi | ~82 ms | yoğun anlarda p90 ~654 ms |
| Binance vadeli fiyat akışı gecikmesi | ~50 ms | |
| Tahmini "karar → emir borsada" | ~163 ms | tahmin; borsanın işlem süresi dahil değil |

Saat ölçümünden dolayı akış gecikmelerinde ±50 ms hata payı var. Bu rakamlar **gerçek emir gecikmesi değil**;
borsanın emri kabul etme süresi ve gerçek dolum oranı ancak `--live` testiyle ölçülür.

## Gerçek test ne yapar?

Tek seferde tahminen 10–20 dakika sürer, BTC 15 dakikalık Yukarı/Aşağı marketlerini kullanır:

1. **Gecikme (20 emir):** fiyatın çok altında, dolmayacak küçük alış teklifi verir → teklifin borsada görünme süresini
   ölçer → iptal eder → silinme süresini ölçer.
2. **Maker dolum (8 emir):** en iyi alış fiyatına 5 hisselik teklif koyar, 30 sn bekler, iptal eder. Gerçek dolumu
   bizim paper modelimizin tahminiyle karşılaştırır.
3. **Taker dolum (4 emir):** $1'lık anında alış (gösterilen en iyi satış fiyatı üst sınır). Gerçekte ne kadarının
   dolduğunu ve hangi fiyattan dolduğunu ölçer.

Sonuçta paper testlerindeki varsayımlar (emir gecikmesi 0,3 sn, iptal 0,2 sn, taker dolumu %100) gerçek değerlerle
karşılaştırılır ve ölçülen değerlerle yeni bir paper ayarı (`variants/measured_<etiket>.json`) yazılır.

## Ne kadar para riske girer?

- Bütçe varsayılan **$15**, en fazla **$50** (kod içinde sabit, komutla artırılamaz). Emir başına en fazla 10 hisse.
- Dolan hisseler satılmaz, market sonuçlanana kadar tutulur → en kötü durumda dolan tutarın tamamı kaybedilebilir
  (yaklaşık **$15'a kadar**). Taker emirlerinde küçük ücret de ödenir.
- Program biterken, hata olursa veya Ctrl+C'ye basılırsa açık emirlerin hepsi iptal edilir.
- Öneri: ayrı, içinde yalnız ~$20–30 olan bir Polymarket hesabı kullanın.

## Kendi bilgisayarınızda adım adım

1. **Python 3.11 veya üstü** kurun (python.org). Windows'ta kurarken "Add Python to PATH" kutusunu işaretleyin.
2. Kodu indirin: GitHub'da `ahmetxm/bot` deposu → `paper-test-v2` dalı → "Code" → "Download ZIP" → klasöre açın.
   (veya: `git clone -b paper-test-v2 https://github.com/ahmetxm/bot.git`)
3. O klasörde bir terminal açın ve kütüphaneleri kurun:
   ```
   pip install polymarket-client websocket-client requests pyyaml numpy
   ```
4. **Önce anahtarsız ölçüm** (emir yok, para yok, ~4 dk):
   ```
   python tools/order_latency_test.py
   ```
   Çıktının ilk satırında `'blocked': False` görmelisiniz. `True` ise durun, gerçek test o konumdan çalışmaz.
5. Klasörde `.env` adlı bir dosya oluşturup iki satır yazın (bu dosya GitHub'a gönderilmez):
   ```
   POLYMARKET_PRIVATE_KEY=0x...özel anahtarınız...
   POLYMARKET_WALLET_ADDRESS=0x...polymarket.com profilinizdeki cüzdan adresi...
   ```
   Özel anahtarı (private key) kimseyle paylaşmayın — bu sohbete de yazmayın.
6. **Gerçek test** (10 sn geri sayım var, bu sürede Ctrl+C ile vazgeçebilirsiniz):
   ```
   python tools/order_latency_test.py --live --i-accept-real-money --budget 15
   ```
7. Bitince `reports` klasöründeki `order_latency_live_...md` ve `.json` dosyalarını bana gönderin
   (anahtar içermezler). Ekrandaki hata mesajı varsa onu da gönderin.

## Bilinmesi gerekenler

- Araç gerçek emirle hiç denenmedi; ilk çalıştırmada beklenmedik bir hata çıkabilir. Hata olursa açık emirler iptal edilir.
- Sonuçlar sizin internet bağlantınızın hızını ölçer. Polymarket'in ana sunucuları Londra'da; Türkiye'den gecikme
  büyük olasılıkla ABD'den daha düşük olacaktır (hipotez, ölçülmedi).
- Bulunduğunuz yerdeki yasal düzenlemeleri kontrol etmek sizin sorumluluğunuzdadır.
- `config.yaml` içindeki `live_trading.enabled` hâlâ `false`; bot kendi başına gerçek işlem yapmaz.
