"""Historical market data for the strategy replica backtest.

* SpotHistory  : Binance 1-second klines (data.binance.vision daily archives, REST fallback
                 for the current day) -> dense per-second close price arrays.
* TapeStore    : every crypto Up/Down market in a time range (gamma API) + its full public
                 taker trade tape (Data API v2 /trades?condition=...) + resolution payouts.

All endpoints are public; nothing here needs an API key.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests

from api_client import PolymarketAPI
from common import TF_SECONDS, load_config, setup_logging, utc

log = logging.getLogger("market_data")

BINANCE_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XRP": "XRPUSDT"}
VISION_URL = "https://data.binance.vision/data/spot/daily/klines/{sym}/1s/{sym}-1s-{day}.zip"
KLINES_REST = "https://data-api.binance.vision/api/v3/klines"


# --------------------------------------------------------------------------- spot
class SpotHistory:
    """Dense 1-second close prices for one asset: price(t) for integer epoch seconds."""

    def __init__(self, t0: int, closes: np.ndarray):
        self.t0 = int(t0)
        self.closes = closes.astype(np.float64)
        self.t1 = self.t0 + len(self.closes) - 1

    def covers(self, a: int, b: int) -> bool:
        return self.t0 <= a and b <= self.t1

    def price(self, t: int) -> float:
        i = min(max(int(t) - self.t0, 0), len(self.closes) - 1)
        return float(self.closes[i])

    def window(self, a: int, b: int) -> np.ndarray:
        """Closes for seconds a..b inclusive (clipped to coverage)."""
        i = max(int(a) - self.t0, 0)
        j = min(int(b) - self.t0, len(self.closes) - 1)
        return self.closes[i:j + 1]

    @staticmethod
    def _parse_kline_csv(raw: bytes) -> tuple[np.ndarray, np.ndarray]:
        arr = np.loadtxt(io.BytesIO(raw), delimiter=",", usecols=(0, 4), dtype=np.float64, ndmin=2)
        ts = arr[:, 0]
        ts = np.where(ts > 1e14, ts / 1e6, ts / 1e3)  # 2025+ archives are in microseconds
        return ts.astype(np.int64), arr[:, 1]

    @classmethod
    def load(cls, asset: str, start: int, end: int, cache_dir: Path) -> "SpotHistory":
        sym = BINANCE_SYMBOL[asset]
        cache_dir.mkdir(parents=True, exist_ok=True)
        ts_parts, px_parts = [], []
        day = datetime.fromtimestamp(start, tz=timezone.utc).date()
        last_day = datetime.fromtimestamp(end, tz=timezone.utc).date()
        sess = requests.Session()
        while day <= last_day:
            dstr = day.isoformat()
            npz = cache_dir / f"{sym}-1s-{dstr}.npz"
            if npz.exists():
                z = np.load(npz)
                ts_parts.append(z["t"]); px_parts.append(z["c"])
            else:
                r = sess.get(VISION_URL.format(sym=sym, day=dstr), timeout=60)
                if r.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                        raw = zf.read(zf.namelist()[0])
                    t, c = cls._parse_kline_csv(raw)
                    np.savez_compressed(npz, t=t, c=c)
                    ts_parts.append(t); px_parts.append(c)
                    log.info("spot %s %s: %d seconds (archive)", sym, dstr, len(t))
                else:  # archive not published yet (current / previous day) -> REST
                    d0 = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
                    t, c = cls._rest_range(sess, sym, max(d0, start - 3700), min(d0 + 86399, end))
                    ts_parts.append(t); px_parts.append(c)
                    log.info("spot %s %s: %d seconds (REST)", sym, dstr, len(t))
            day += timedelta(days=1)
        t = np.concatenate(ts_parts); c = np.concatenate(px_parts)
        order = np.argsort(t, kind="stable")
        t, c = t[order], c[order]
        t0, t1 = int(t[0]), int(t[-1])
        dense = np.full(t1 - t0 + 1, np.nan)
        dense[t - t0] = c
        # forward-fill seconds without trades
        idx = np.where(~np.isnan(dense), np.arange(len(dense)), 0)
        np.maximum.accumulate(idx, out=idx)
        dense = dense[idx]
        return cls(t0, dense)

    @staticmethod
    def _rest_range(sess: requests.Session, sym: str, a: int, b: int) -> tuple[np.ndarray, np.ndarray]:
        ts, px = [], []
        cur = a * 1000
        while cur <= b * 1000:
            r = sess.get(KLINES_REST, params={"symbol": sym, "interval": "1s", "startTime": cur,
                                              "endTime": b * 1000, "limit": 1000}, timeout=30)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for k in rows:
                ts.append(int(k[0]) // 1000); px.append(float(k[4]))
            cur = int(rows[-1][0]) + 1000
            time.sleep(0.05)
        return np.array(ts, dtype=np.int64), np.array(px, dtype=np.float64)


# --------------------------------------------------------------------------- tapes
class TapeStore:
    """Up/Down market metadata + full taker trade tapes, cached on disk (data/tapes)."""

    def __init__(self, cfg: dict, api: Optional[PolymarketAPI] = None):
        self.cfg = cfg
        self.api = api or PolymarketAPI(cfg)
        self.dir = Path(cfg["paths"]["data_dir"]) / "tapes"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"

    def load_index(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {}

    def save_index(self, idx: dict) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx))
        tmp.replace(self.index_path)

    # ---- market discovery
    def discover(self, assets: list[str], timeframes: list[str], start: int, end: int) -> dict:
        """Resolve every <asset>-updown-<tf>-<epoch> market whose window lies in [start, end)."""
        idx = self.load_index()
        slugs = []
        for a in assets:
            for tf in timeframes:
                sec = TF_SECONDS[tf]
                t = start - start % sec
                while t + sec <= end:
                    slug = f"{a.lower()}-updown-{tf}-{t}"
                    if slug not in idx or not idx[slug].get("payouts"):
                        slugs.append(slug)
                    t += sec
        log.info("discover: %d markets to resolve via gamma", len(slugs))
        for i in range(0, len(slugs), 20):
            batch = slugs[i:i + 20]
            params = [("slug", s) for s in batch] + [("closed", "true"), ("limit", 40)]
            res = self.api.get(f"{self.api.gamma_api}/markets", params) or []
            for m in res:
                slug = m.get("slug")
                try:
                    toks = json.loads(m.get("clobTokenIds") or "[]")
                    outs = json.loads(m.get("outcomes") or "[]")
                    prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
                except (ValueError, TypeError):
                    continue
                payouts = prices if prices and abs(sum(prices) - 1) < 1e-6 and max(prices) == 1.0 else None
                asset, tf, epoch = slug.split("-")[0].upper(), slug.split("-")[2], int(slug.split("-")[-1])
                fee = m.get("feeSchedule") or {}
                idx[slug] = {
                    "slug": slug, "condition_id": m.get("conditionId"), "tokens": toks, "outcomes": outs,
                    "asset": asset, "timeframe": tf, "window_start": epoch,
                    "window_end": epoch + TF_SECONDS[tf], "payouts": payouts,
                    "fee_rate": float(fee.get("rate", 0.0) or 0.0),
                    "volume": float(m.get("volume") or 0.0),
                    "tick": float(m.get("orderPriceMinTickSize") or 0.01),
                    "min_size": float(m.get("orderMinSize") or 5),
                    "twap_lookback": int((m.get("cryptoMarketConfig") or {}).get("twapLookbackSeconds") or 0),
                }
            if (i // 20) % 10 == 0:
                self.save_index(idx)
        self.save_index(idx)
        return idx

    # ---- tapes
    def tape_path(self, slug: str) -> Path:
        return self.dir / f"{slug}.json.gz"

    def fetch_tape(self, meta: dict) -> int:
        path = self.tape_path(meta["slug"])
        if path.exists():
            return -1
        rows, cursor = [], None
        while True:
            params = {"condition": meta["condition_id"]}
            if cursor:
                params["cursor"] = cursor
            else:
                params["limit"] = 1000
            page = self.api.get(f"{self.api.data_api}/trades", params)
            for r in page.get("data") or []:
                rows.append([int(r["timestamp"]), r["side"], int(r["outcome_index"]),
                             float(r["price"]), float(r["size"])])
            cursor = (page.get("pagination") or {}).get("next_cursor")
            if not cursor:
                break
        rows.sort(key=lambda x: x[0])
        with gzip.open(path, "wt") as fh:
            json.dump(rows, fh)
        return len(rows)

    def load_tape(self, slug: str) -> list:
        with gzip.open(self.tape_path(slug), "rt") as fh:
            return json.load(fh)

    def fetch_all(self, idx: dict, workers: int = 4) -> None:
        todo = [m for m in idx.values() if m.get("payouts") and m.get("condition_id")
                and not self.tape_path(m["slug"]).exists()]
        log.info("tapes: %d to download (%d already cached)", len(todo),
                 sum(1 for m in idx.values() if self.tape_path(m["slug"]).exists()))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self.fetch_tape, m): m["slug"] for m in todo}
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception as exc:  # keep going; a missing tape just drops that market
                    log.warning("tape %s failed: %s", futs[f], exc)
                done += 1
                if done % 100 == 0:
                    log.info("tapes: %d/%d", done, len(todo))


def resolve_range(cfg: dict, days: Optional[float] = None) -> tuple[int, int]:
    scfg = cfg["strategy_backtest"]
    now = int(time.time())
    end = now - int(scfg.get("end_lag_minutes", 30)) * 60
    d = float(days if days is not None else scfg["days"])
    return end - int(d * 86400), end


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Download spot + market tapes for the strategy backtest")
    ap.add_argument("--days", type=float, default=None)
    args = ap.parse_args(argv)
    cfg = load_config()
    setup_logging(cfg, "market_data")
    scfg = cfg["strategy_backtest"]
    start, end = resolve_range(cfg, args.days)
    log.info("range %s -> %s", utc(start), utc(end))
    store = TapeStore(cfg)
    idx = store.discover(scfg["assets"], scfg["timeframes"], start, end)
    store.fetch_all(idx, workers=int(cfg["collect"].get("workers", 4)))
    for a in scfg["assets"]:
        sp = SpotHistory.load(a, start - 3700, end, Path(cfg["paths"]["data_dir"]) / "spot")
        log.info("spot %s coverage %s -> %s", a, utc(sp.t0), utc(sp.t1))
    log.info("done (%d API requests)", store.api.request_count)


if __name__ == "__main__":
    main()
