"""Why can't the replica match the target wallet? Three measurements, one Turkish report.

A) Fill quality, same yardstick for both: for every fill, the edge per share vs. our spot-based fair value at
   the fill, 30 s later (markout) and at resolution (payout - price). Target: its own March 2026 fills (BTC/ETH
   5m/15m, Data API timestamps shifted 2 s earlier). Replica: our live paper fills (24 Nov 2026).
B) Speed ceiling: the Nov 2026 tape backtest re-run as if we were always FIRST in the queue and (almost)
   instant, with and without the 20 % maker rebate. If even that loses, speed alone cannot close the gap.
C) Market rules then vs. now (Gamma API): resolution rule and fee curve.

    python tools/performance_gap.py            # -> reports/performance_gap.md / .json
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import strategy_backtest as sb  # noqa: E402
from common import load_config, save_json, setup_logging, utc  # noqa: E402
from fair_value import ewma_variance, fair_up_series  # noqa: E402
from market_data import SpotHistory  # noqa: E402
from pair_strategy import StrategyParams  # noqa: E402

SLUG_RE = re.compile(r"^(btc|eth)-updown-(5m|15m)-(\d+)$")
VOL_HL, VOL_MULT, VOL_FLOOR = 600, 1.0, 0.35e-4
API_LAG = 2            # Data API timestamps trail the match by ~2 s (measured median 2.2 s)
MARKOUT = 30


# --------------------------------------------------------------------------- spot helpers
def spot_from_zips(asset: str, spot_dir: Path):
    parts = []
    for z in sorted(spot_dir.glob(f"{asset}USDT-1s-2026-03-*.zip")):
        with zipfile.ZipFile(z) as zf:
            df = pd.read_csv(io.BytesIO(zf.read(zf.namelist()[0])), header=None, usecols=[0, 4])
        t = df[0].to_numpy(np.float64)
        t = np.where(t > 1e14, t / 1e6, t / 1e3).astype(np.int64)
        parts.append((t, df[4].to_numpy(np.float64)))
    if not parts:
        return None
    t = np.concatenate([p[0] for p in parts]); c = np.concatenate([p[1] for p in parts])
    o = np.argsort(t, kind="stable"); t, c = t[o], c[o]
    dense = np.full(t[-1] - t[0] + 1, np.nan); dense[t - t[0]] = c
    idx = np.where(~np.isnan(dense), np.arange(len(dense)), 0); np.maximum.accumulate(idx, out=idx)
    return SpotHistory(int(t[0]), dense[idx])


class FairCache:
    def __init__(self, spot: dict):
        self.spot = {a: s for a, s in spot.items() if s is not None}
        self.lc = {a: np.log(s.closes) for a, s in self.spot.items()}
        self.ev = {a: ewma_variance(self.lc[a], VOL_HL) for a in self.spot}
        self.cache: dict = {}

    def series(self, asset: str, ws: int, we: int, twap: int):
        key = (asset, ws, we)
        if key not in self.cache:
            sp = self.spot.get(asset)
            ok = sp is not None and sp.covers(ws - max(twap, 1) - 10, we)
            self.cache[key] = (fair_up_series(self.lc[asset], self.ev[asset], sp.t0, ws, we, ws, we, twap,
                                              VOL_MULT, VOL_FLOOR) if ok else None)
        return self.cache[key]


def fill_metrics(fills: pd.DataFrame, fc: FairCache, lag: float) -> pd.DataFrame:
    """fills: asset, ws, we, twap, t, side, oi, price, size, payout_up (+ fee_ps optional)."""
    rows = []
    for r in fills.itertuples(index=False):
        f = fc.series(r.asset, r.ws, r.we, r.twap)
        if f is None:
            continue
        t = int(np.clip(int(np.floor(r.t - lag)), r.ws, r.we))
        fu0, fu1 = f[t - r.ws], f[min(t + MARKOUT, r.we) - r.ws]
        fo0, fo1 = (fu0, fu1) if r.oi == 0 else (1 - fu0, 1 - fu1)
        pay = r.payout_up if r.oi == 0 else 1 - r.payout_up
        sg = 1.0 if r.side == "BUY" else -1.0
        rows.append({"role": r.role, "side": r.side, "cat": r.cat, "size": r.size, "price": r.price,
                     "edge_fill": sg * (fo0 - r.price), "edge_30s": sg * (fo1 - r.price),
                     "edge_final": sg * (pay - r.price), "fee_ps": getattr(r, "fee_ps", 0.0),
                     "secs_left": r.we - t, "group": getattr(r, "group", "")})
    return pd.DataFrame(rows)


def agg(df: pd.DataFrame, by: list) -> list:
    out = []
    if df.empty:
        return out
    for k, g in df.groupby(by, observed=True):
        w = g["size"].to_numpy()
        wm = lambda c: float(np.average(g[c], weights=w)) if w.sum() > 0 else float("nan")  # noqa: E731
        out.append({**dict(zip(by, k if isinstance(k, tuple) else (k,))), "fills": len(g), "shares": float(w.sum()),
                    "avg_price": wm("price"), "edge_fill_c": 100 * wm("edge_fill"), "edge_30s_c": 100 * wm("edge_30s"),
                    "edge_final_c": 100 * wm("edge_final"), "fee_c": 100 * wm("fee_ps"),
                    "adverse_30s_c": 100 * (wm("edge_30s") - wm("edge_fill"))})
    return out


# --------------------------------------------------------------------------- A1: target (March 2026)
def target_fills(cfg, log) -> pd.DataFrame:
    data = Path(cfg["paths"]["data_dir"])
    df = pd.read_csv(data / "trades.csv.gz")
    mk = json.loads((data / "markets.json").read_text())
    m = df["slug"].astype(str).str.extract(SLUG_RE.pattern)
    df = df[m[0].notna()].copy()
    m = m[m[0].notna()]
    df["asset"] = m[0].str.upper(); df["cat"] = df["asset"] + " " + m[1]
    df["ws"] = df["condition_id"].map(lambda c: (mk.get(c) or {}).get("window_start"))
    df["we"] = df["condition_id"].map(lambda c: (mk.get(c) or {}).get("window_end"))

    def pu(c):
        p = (mk.get(c) or {}).get("payouts")
        return (float(p[0]) / (float(p[0]) + float(p[1]))) if p and (float(p[0]) + float(p[1])) > 0 else np.nan
    df["payout_up"] = df["condition_id"].map(pu)
    df = df.dropna(subset=["ws", "we", "payout_up"])
    df["ws"] = df["ws"].astype(int); df["we"] = df["we"].astype(int)
    df = df.rename(columns={"timestamp": "t", "outcome_index": "oi"})
    df["twap"] = 0                       # March markets: no cryptoMarketConfig -> start/end price
    # fee the target paid as taker under the March curve: 0.25 * (p(1-p))^2 per share
    p = df["price"].clip(0, 1)
    df["fee_ps"] = np.where(df["role"] == "taker", 0.25 * (p * (1 - p)) ** 2, 0.0)
    df["fee_now_ps"] = np.where(df["role"] == "taker",
                                np.where(df["asset"] == "BTC", 0.05, 0.01) * p * (1 - p), 0.0)
    log.info("target: %d BTC/ETH 5m/15m fills with resolutions", len(df))
    return df


# --------------------------------------------------------------------------- A2: replica (Nov 2026 live paper)
def replica_fills(cfg, log) -> pd.DataFrame:
    data = Path(cfg["paths"]["data_dir"])
    outcome: dict = {}
    for st in data.glob("live_paper_state*.json"):
        try:
            s = json.loads(st.read_text())
        except ValueError:
            continue
        for slug, v in (s.get("markets") or {}).items():
            if v.get("status") == "settled" and v.get("outcome_up") is not None:
                outcome[slug] = float(v["outcome_up"])
    frames = []
    groups = {"replica": "80 dk test (sabah)", "makeronly": "80 dk sadece maker"}
    for p in sorted(data.glob("live_paper_fills_*.csv")):
        tag = p.stem.replace("live_paper_fills_", "")
        if tag.startswith("smoke"):
            continue
        d = pd.read_csv(p)
        if d.empty:
            continue
        d["group"] = groups.get(tag, tag)
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    missing = sorted(set(df["slug"]) - set(outcome))
    for slug in missing:          # settle the rest from Gamma (closed markets)
        try:
            ev = requests.get("https://gamma-api.polymarket.com/events", params={"slug": slug}, timeout=15).json()
            op = json.loads(ev[0]["markets"][0].get("outcomePrices") or "[]")
            if op and ev[0]["markets"][0].get("closed") and float(op[0]) in (0.0, 1.0):
                outcome[slug] = float(op[0])
        except (requests.RequestException, ValueError, KeyError, IndexError):
            pass
    m = df["slug"].str.extract(SLUG_RE.pattern)
    df["asset"] = m[0].str.upper(); df["cat"] = df["asset"] + " " + m[1]
    df["ws"] = m[2].astype(int); df["we"] = df["ws"] + np.where(m[1] == "5m", 300, 900)
    df["payout_up"] = df["slug"].map(outcome)
    df = df.dropna(subset=["payout_up"])
    df = df.rename(columns={"ts": "t", "shares": "size"})
    df["oi"] = (df["outcome"] == "Down").astype(int)
    df["twap"] = 60
    df["fee_ps"] = df["fee"] / df["size"].clip(lower=1e-9)
    log.info("replica: %d live paper fills in settled markets (%d markets unresolved skipped)",
             len(df), len(missing))
    return df


# --------------------------------------------------------------------------- B: speed ceiling
def speed_ceiling(cfg, log) -> dict:
    sb._BT = dict(cfg["strategy_backtest"])
    sb._MARKETS, sb._SPOT = sb.load_universe(cfg, None)
    n = len(sb._MARKETS); split = int(n * float(sb._BT.get("train_fraction", 0.6)))
    idx_all, idx_test = list(range(n)), list(range(split, n))
    start_balance = float(cfg["paper_trading"]["starting_balance"])
    budget = min(float(cfg["risk"]["max_position_pct"]) * start_balance, float(cfg["pair_strategy"]["max_market_usd"]))
    data = Path(cfg["paths"]["data_dir"])
    v1 = StrategyParams(**json.loads((data / "calibrated_params.json").read_text())["params"])
    tk = StrategyParams(**json.loads((data / "calibrated_params_v2_fixed3.json").read_text())["params"])
    allc = ["BTC 5m", "BTC 15m", "ETH 5m", "ETH 15m"]
    strategies = {"v1 maker+taker (canlı testteki)": v1, "sadece taker BTC (v2)": tk}
    for hs in (0.01, 0.02, 0.03, 0.05):
        strategies[f"sadece maker, fiyat farkı {hs:.2f}"] = StrategyParams(**{
            **v1.as_dict(), "markets": allc, "half_spread": hs, "take_enabled": False, "guard_move": 0.0})
    f3 = {"_lag_samples": None, "tape_timestamp_lag_seconds": 3}
    scen = {"bugünkü varsayım (kuyruk sonu, 1 sn)": {**f3},
            "kuyrukta ilk sıra, 1 sn": {**f3, "queue_fill_fraction": 1.0},
            "ilk sıra + en hızlı tepki (veri çözünürlüğü 1 sn)": {**f3, "queue_fill_fraction": 1.0, "latency_seconds": 0},
            "ilk sıra + en hızlı + %20 maker rebate": {**f3, "queue_fill_fraction": 1.0, "latency_seconds": 0,
                                                     "maker_rebate_rate": 0.2},
            "ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser)": {
                "_lag_samples": None, "tape_timestamp_lag_seconds": 2, "queue_fill_fraction": 1.0,
                "latency_seconds": 0, "maker_rebate_rate": 0.2}}
    out = {"markets": n, "test_markets": len(idx_test), "from": utc(sb._MARKETS[0][0]["window_start"]),
           "to": utc(sb._MARKETS[-1][0]["window_end"]), "rows": []}
    with get_context("fork").Pool(30) as pool:
        for sname, sp in strategies.items():
            for cname, over in scen.items():
                row = {"strategy": sname, "scenario": cname}
                for part, idxs in (("all", idx_all), ("test", idx_test)):
                    sm = sb.summarize(sb.run_params(pool, idxs, sp, budget, over), start_balance, None)
                    row[part] = {k: sm[k] for k in ("pnl", "roi_on_buys_pct", "markets_traded", "maker_fills",
                                                     "taker_fills", "fees", "rebates", "win_rate_pct")}
                out["rows"].append(row)
                log.info("ceiling %-38s | %-55s | all %+8.0f (%.2f%%) | test %+8.0f", sname, cname,
                         row["all"]["pnl"], row["all"]["roi_on_buys_pct"], row["test"]["pnl"])
    return out


# --------------------------------------------------------------------------- C: market rules
def market_rules() -> list:
    rows = []
    for slug in ("btc-updown-5m-1774354200", "btc-updown-15m-1774353600", "btc-updown-5m-1795532100",
                 "eth-updown-5m-1795532100"):
        try:
            m = requests.get("https://gamma-api.polymarket.com/events", params={"slug": slug}, timeout=15).json()[0]["markets"][0]
            rows.append({"slug": slug, "twap": (m.get("cryptoMarketConfig") or {}).get("twapLookbackSeconds", 0),
                         "fee": m.get("feeSchedule"), "tick": m.get("orderPriceMinTickSize")})
        except (requests.RequestException, ValueError, KeyError, IndexError):
            rows.append({"slug": slug, "error": "unavailable"})
    return rows


# --------------------------------------------------------------------------- report
def c(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{d}f}".replace(".", ",")


def money(x):
    s = f"{abs(x):,.0f}".replace(",", ".")
    return f"{'−' if x < 0 else '+'}${s}"


def write_report(res: dict, path: Path) -> None:
    L = ["# Neden hedefin performansını yakalayamıyoruz? — ölçüm raporu", "",
         f"Oluşturma: {res['generated_at']}. Gerçek emir yok. Rakamlar paylaşım (share) başına **sent** cinsindendir "
         "(1 sent = $0,01); pozitif = bizim lehimize.", "",
         "## 1. Piyasa kuralları değişti (Gamma API)", "",
         "| market | sonuçlanma kuralı | taker ücret eğrisi | fiyat adımı |", "|---|---|---|---|"]
    for r in res["rules"]:
        if "error" in r:
            continue
        fee = r["fee"] or {}
        curve = f"{fee.get('rate')} × (p(1−p))^{fee.get('exponent')}, maker rebate %{int(100 * (fee.get('rebateRate') or 0))}"
        L.append(f"| {r['slug']} | {'son ' + str(r['twap']) + ' sn ortalaması (TWAP)' if r['twap'] else 'pencere sonu tek fiyat'} "
                 f"| {curve} | {r['tick']} |")
    tf = res["target_fee_compare"]
    L += ["", f"Hedefin taker işlemlerinde ödediği ortalama ücret: Mart eğrisiyle **{c(tf['march_c'])} sent/share**, "
          f"aynı işlemler bugünkü eğriyle **{c(tf['now_c'])} sent/share** olurdu.", "",
          "## 2. İşlem kalitesi: hedef (Mart 2026) vs bizim bot (24 Kasım 2026 canlı paper)", "",
          "Aynı adil değer modeliyle ölçüldü. *İşlem anı*: adil değer − fiyat. *30 sn sonra*: 30 sn sonraki adil değer − fiyat. "
          "*Sonuç*: market sonucu (0/1) − fiyat (ücret hariç). *30 sn kayma*: 30 sn sonra − işlem anı "
          "(eksi = işlemden sonra fiyat aleyhimize döndü, yani ters seçim).", "",
          "| kim | rol | fill | share | ort. fiyat | işlem anı | 30 sn sonra | 30 sn kayma | sonuç (ücret hariç) | ücret |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for who, rows in (("hedef", res["target_by_role"]), ("bizim bot", res["replica_by_role"])):
        for r in rows:
            L.append(f"| {who} | {r['role']} | {r['fills']:,} | {r['shares']:,.0f} | {r['avg_price']:.3f} | {c(r['edge_fill_c'])} | "
                     f"{c(r['edge_30s_c'])} | {c(r['adverse_30s_c'])} | {c(r['edge_final_c'])} | {c(r['fee_c'])} |")
    L += ["", "### Kategoriye göre (sonuç − fiyat, sent/share, ücret hariç)", "",
          "| kim | kategori | rol | fill | işlem anı | 30 sn sonra | sonuç |", "|---|---|---|---:|---:|---:|---:|"]
    for who, rows in (("hedef", res["target_by_cat"]), ("bizim bot", res["replica_by_cat"])):
        for r in rows:
            L.append(f"| {who} | {r['cat']} | {r['role']} | {r['fills']:,} | {c(r['edge_fill_c'])} | {c(r['edge_30s_c'])} | "
                     f"{c(r['edge_final_c'])} |")
    L += ["", "### Hedefin işlemleri: pencerenin neresinde? (sent/share, ücret hariç)", "",
          "| rol | kalan süre | fill | işlem anı | 30 sn sonra | sonuç |", "|---|---|---:|---:|---:|---:|"]
    for r in res["target_by_time"]:
        L.append(f"| {r['role']} | {r['bucket']} | {r['fills']:,} | {c(r['edge_fill_c'])} | {c(r['edge_30s_c'])} | "
                 f"{c(r['edge_final_c'])} |")
    sc = res["speed_ceiling"]
    L += ["", f"## 3. Hız tavanı: \"kuyrukta hep ilk sıradayız ve anında işlem yapıyoruz\" (backtest, {sc['markets']} market, "
          f"{sc['from']} → {sc['to']}; son {sc['test_markets']} market = test)", "",
          "| strateji | senaryo | tüm dönem PnL | alımlara göre | test PnL | maker / taker fill | rebate |",
          "|---|---|---:|---:|---:|---:|---:|"]
    for r in sc["rows"]:
        a, t = r["all"], r["test"]
        L.append(f"| {r['strategy']} | {r['scenario']} | {money(a['pnl'])} | {c(a['roi_on_buys_pct'])}% | {money(t['pnl'])} | "
                 f"{a['maker_fills']:,} / {a['taker_fills']:,} | ${a['rebates']:,.0f} |")
    L += ["", "## 4. Yorum", ""] + res["conclusions"] + [
        "", "## Varsayımlar ve sınırlar",
        "- Hedefin Data API zaman damgaları 2 sn geri kaydırıldı (ölçülen medyan gecikme 2,2 sn). Mart marketleri tek fiyatla "
        "sonuçlandığı için adil değer TWAP'sız hesaplandı; Binance fiyatı Chainlink'in yerine kullanıldı.",
        "- Hedefin maker rebate gelirleri işlem verisinde görünmez; yukarıdaki hedef rakamları rebate hariçtir.",
        "- Hız tavanı bir üst sınırdır: geçmiş işlemlerin bizim emrimiz olsaydı da aynen gerçekleşeceği varsayılır.",
        "- Bizim canlı örneğimiz küçük (birkaç yüz fill); hedefinki yüz binlerce fill."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def build_conclusions(res: dict) -> list:
    tr = {r["role"]: r for r in res["target_by_role"]}
    rr = {r["role"]: r for r in res["replica_by_role"]}
    tp = res["target_pnl"]
    net = {k: v["gross"] - v["fees"] for k, v in tp.items()}   # $ (shares x $/share)
    rows = {(r["strategy"], r["scenario"]): r for r in res["speed_ceiling"]["rows"]}
    v1 = "v1 maker+taker (canlı testteki)"
    cons = rows.get((v1, "ilk sıra + en hızlı + %20 maker rebate"))
    opt = rows.get((v1, "ilk sıra + en hızlı + rebate + 1 sn daha erken (iyimser)"))
    mk = [r for r in res["speed_ceiling"]["rows"] if r["strategy"].startswith("sadece maker")]
    mk_cons = max((r for r in mk if r["scenario"] == "ilk sıra + en hızlı + %20 maker rebate"),
                  key=lambda r: r["all"]["pnl"], default=None)
    late = [r for r in res["target_by_time"] if r["role"] == "maker" and r["bucket"] in ("son 30 sn", "30–60 sn")]
    tf = res["target_fee_compare"]
    L = []
    if "maker" in net and "taker" in net:
        L.append(f"- **Hedefin kârının kaynağı:** 17–24 Mart BTC/ETH işlemlerinde maker tarafı "
                 f"{money(net['maker'])} (share başına {c(tr['maker']['edge_final_c'])} sent; işlemden 30 sn sonraki kayma "
                 f"{c(tr['maker']['adverse_30s_c'])} sent{', yani ters seçim yok' if tr['maker']['adverse_30s_c'] > -0.1 else ''}), "
                 f"taker tarafı ücret sonrası {money(net['taker'])}. Toplam "
                 f"{money(net['maker'] + net['taker'])} (maker rebate hariç).")
    if late and all(r["edge_final_c"] < 0 for r in late):
        L.append("- **Son dakika değil, pencerenin başı/ortası:** hedefin son 60 sn'deki maker işlemleri zarar ettirmiş ("
                 + ", ".join(f"{r['bucket']}: {c(r['edge_final_c'])}" for r in late)
                 + " sent/share); kâr 2–15 dk kala verilen tekliflerden. Yani yeni TWAP kuralı tek başına açıklama değil.")
    cheaper = tf["now_c"] <= tf["march_c"]
    L.append(f"- **Ücret {'engel değil' if cheaper else 'arttı'}:** hedefin taker ücreti Mart eğrisiyle {c(tf['march_c'])} "
             f"sent/share idi; bugünkü eğriyle {c(tf['now_c'])} olurdu ({'daha ucuz' if cheaper else 'daha pahalı'}).")
    if "taker" in rr and "taker" in tr:
        L.append(f"- **Bizim sinyalimiz daha gürültülü/geç:** bizim taker işlemlerimizde model işlem anında "
                 f"{c(rr['taker']['edge_fill_c'])} sent avantaj görüyor ama bu 30 sn içinde {c(rr['taker']['adverse_30s_c'])} "
                 f"sent değişiyor; hedefin taker işlemlerinde aynı ölçü {c(tr['taker']['adverse_30s_c'])} sent "
                 "(fiyat hedefin lehine gitmeye devam etmiş). Hedef fiyat hareketini bizden önce görüp işlem yapıyordu (hipotez).")
    if cons and opt:
        L.append(f"- **Her şey ~1 saniyeye bağlı (backtest, Kasım verisi):** canlı testteki strateji kuyrukta hep ilk sırada, "
                 f"en hızlı tepkiyle ve %20 rebate ile bile tüm dönemde {money(cons['all']['pnl'])} "
                 f"({c(cons['all']['roi_on_buys_pct'])}%); aynı şey 1 sn daha erken davranabilseydik "
                 f"{money(opt['all']['pnl'])} ({c(opt['all']['roi_on_buys_pct'])}%, test {money(opt['test']['pnl'])}). "
                 "Geçmiş veri bu 1 saniyeyi güvenilir ayırt edemiyor; bunu ancak gerçek emir gösterir.")
    if mk_cons:
        L.append(f"- **Sadece maker (hedefin yaptığı) bugün muhafazakâr varsayımla zarar:** en iyi fiyat farkıyla bile "
                 f"{money(mk_cons['all']['pnl'])} ({mk_cons['strategy']}).")
    if "maker" in rr:
        L.append(f"- **Bizim canlı maker örneğimiz çok küçük** ({rr['maker']['fills']} fill); sonucu ({c(rr['maker']['edge_final_c'])} "
                 "sent/share) şans payı çok yüksek, karar için yeterli değil.")
    return L


def main():
    cfg = load_config()
    log = setup_logging(cfg, "performance_gap")
    t0 = time.time()
    data = Path(cfg["paths"]["data_dir"])
    res: dict = {"generated_at": utc(time.time())}
    res["rules"] = market_rules()

    tgt = target_fills(cfg, log)
    tk = tgt[tgt["role"] == "taker"]
    res["target_fee_compare"] = {"march_c": 100 * float(np.average(tk["fee_ps"], weights=tk["size"])),
                                 "now_c": 100 * float(np.average(tk["fee_now_ps"], weights=tk["size"]))}
    fc_m = FairCache({a: spot_from_zips(a, data / "spot") for a in ("BTC", "ETH")})
    tm = fill_metrics(tgt, fc_m, API_LAG)
    log.info("target fills with spot coverage: %d", len(tm))
    res["target_by_role"] = agg(tm, ["role"])
    res["target_by_cat"] = agg(tm, ["cat", "role"])
    tmk = tm.copy()
    tmk["bucket"] = pd.cut(tmk["secs_left"], [-1, 30, 60, 120, 300, 900],
                           labels=["son 30 sn", "30–60 sn", "1–2 dk", "2–5 dk", "5–15 dk"])
    res["target_by_time"] = agg(tmk, ["role", "bucket"])
    # what the target actually earned on these fills (excl. rebates): sum(size * (payout - price)) - fees
    res["target_pnl"] = {role: {"shares": float(g["size"].sum()),
                                "gross": float((g["size"] * g["edge_final"]).sum()),
                                "fees": float((g["size"] * g["fee_ps"]).sum())}
                         for role, g in tm.groupby("role")}

    rep = replica_fills(cfg, log)
    lo, hi = int(rep["ws"].min()) - 4000, int(rep["we"].max()) + 60
    fc_n = FairCache({a: SpotHistory.load(a, lo, hi, data / "spot") for a in ("BTC", "ETH")})
    rm = fill_metrics(rep, fc_n, 0.0)
    res["replica_by_role"] = agg(rm, ["role"])
    res["replica_by_cat"] = agg(rm, ["cat", "role"])
    res["replica_by_group"] = agg(rm, ["group", "role"])

    res["speed_ceiling"] = speed_ceiling(cfg, log)

    # ---- conclusions from the numbers
    res["conclusions"] = build_conclusions(res)
    res["runtime_seconds"] = round(time.time() - t0, 1)
    rp = Path(cfg["paths"]["reports_dir"])
    save_json(res, rp / "performance_gap.json")
    write_report(res, rp / "performance_gap.md")
    log.info("done in %.0f s -> reports/performance_gap.md", res["runtime_seconds"])


if __name__ == "__main__":
    main()
