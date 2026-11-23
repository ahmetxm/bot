# Polymarket Copy-Trade Bot (Python, paper trading)

Hedef cüzdan: `0xd0d6053c3c37e727402d84c14069780d360993aa` (k9Q2mX4L8A7ZP3R)

Bot, hedef cüzdanın işlemlerini Polymarket Data API v2 üzerinden 10 saniyede bir yoklar ve aynı pozisyonları
orantılı ölçekle sanal bir portföyde açar. Ayrıca geçmiş veriyi toplar, stratejiyi analiz eder ve backtest yapar.
Doğrudan `requests` kullanılır (SDK yok); tüm istekler hız sınırlamalı (rate-limited) ve yeniden denemelidir.

## Kurulum ve kullanım

```bash
cd polymarket_bot
pip install -r requirements.txt

python main.py collect                    # trade geçmişi + market bilgileri + PnL verisi  -> data/
python main.py collect --max-trades 2000  # hızlı test
python main.py analyze                    # strateji analizi -> reports/strategy_analysis.{json,md}, charts/
python main.py backtest                   # son 7 gün backtest -> reports/backtest_report.md, performance_report.json
python main.py run --mode paper           # canlı veriyle paper trading (Ctrl+C ile durur)
python main.py run --mode paper --duration 3600
python main.py run --mode live            # VARSAYILAN OLARAK KAPALI (aşağıya bakın)

python run_test.py                        # uçtan uca: (gerekirse) collect -> analyze -> backtest
python tests/test_copy_bot.py             # ağ gerektirmeyen birim/entegrasyon testleri
```

Tüm ayarlar `config.yaml` içindedir.

## Dosyalar

| Dosya | Görev |
|---|---|
| `data_collector.py` | `/v2/trades` (keyset pagination, maker+taker fill'ler), `/resolutions`, `/v2/tokens`, gamma `/markets`, kullanıcı PnL serisi |
| `strategy_analyzer.py` | market dağılımı, BUY/SELL, büyüklükler, frekans, saatlik pattern, giriş zamanlaması, kazanma oranı, PnL dağılımı |
| `bot.py` | `CopyEngine` (kopyalama mantığı, backtest ile ortak), `CopyTradeBot` (polling), `LiveExecutor` (korumalı) |
| `paper_trader.py` | sanal portföy, risk limitleri, PnL, Sharpe, max drawdown, işlem logu |
| `run_test.py` | backtest senaryoları + performans raporu |
| `main.py` | CLI |
| `api_client.py`, `common.py` | HTTP istemcisi (throttle/retry), ortak yardımcılar, fee modeli |

## Risk limitleri (`config.yaml -> risk`)

- **Max pozisyon:** market başına özsermayenin %10'u (emirler kırpılır)
- **Max günlük kayıp:** $500 — UTC günü içinde gerçekleşen zarar bu sınıra ulaşınca yeni girişler gün sonuna kadar durdurulur
- **Stop-loss:** tek pozisyonun gerçekleşmemiş zararı özsermayenin %5'ini aşarsa UYARI (`stop_loss_action: close` ile otomatik kapatma)
- **Min emir:** 5 hisse / $1 (küçük kopyalar biriktirilir)

## Live mod güvenliği

Live mod iki ayrı kilitle kapalıdır:
1. `config.yaml -> live_trading.enabled: false` (varsayılan). Bu `false` iken `--mode live` reddedilir (çıkış kodu 2).
2. Anahtarlar sadece ortam değişkenlerinden okunur, kodda/config'de tutulmaz:
   `POLY_PRIVATE_KEY`, `POLY_FUNDER_ADDRESS`, opsiyonel `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`.
   Emir imzalamak için `pip install py-clob-client` gerekir.

Live modu açmadan önce paper modda en az birkaç gün sonuç toplayın. Live yürütme kodu bu projede gerçek emirle test edilmemiştir.

## Backtest senaryoları

| Senaryo | Açıklama |
|---|---|
| `target_replica` | hedefin kendi fill'lerinin yeniden oynatılması (doğrulama + hedefin kullandığı sermaye tahmini) |
| `ideal_copy` | $10k hesap, anında ve aynı fiyattan kopya, ücretsiz (teorik üst sınır) |
| `realistic_copy` | 10 s polling + 2 s gecikme, sonraki market fiyatı + 30 bps kayma, taker ücreti, tüm risk limitleri |
| `realistic_taker_only` | aynı, ama sadece hedefin taker fill'leri kopyalanır |
| `diag_fill_price_with_fees` | teşhis: hedefin fiyatı + taker ücreti (sadece ücretin etkisi) |
| `diag_realistic_no_loss_halt` | teşhis: realistic_copy, günlük zarar durdurması olmadan |

Taker ücreti: `hisse × oran × p × (1−p)`; BTC 5m/15m için oran 0.05, diğer kripto için 0.01. Maker'lar ücret ödemez.

## Önemli bulgular (ayrıntılar `reports/` altında)

- Cüzdan, Polymarket verisine göre 2026-03-24'ten beri fiilen pasif (son tekil fill 2026-04-06). Canlı bot çalışır,
  ancak kopyalanacak yeni işlem gelmez.
- Gerçek davranış "ortalama ~$30k/trade latency-arb" tanımıyla uyuşmuyor: kripto Up/Down marketlerinde çoğunlukla
  **maker** olarak küçük fill'lerle (medyan ~$4) iki tarafı da alan bir market-making botu.
- Hedefin kârı maker konumundan (ücret yok + rebate) ve saniyenin altındaki hızından geliyor. 10 saniyelik polling ile
  taker emri veren bir takipçi, backtestte bu avantajı yakalayamadı ve zarar etti (bkz. `reports/backtest_report.md`).
