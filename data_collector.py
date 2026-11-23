"""Data collection: full trade history of the target wallet + market metadata/resolutions.

Outputs (data/):
  trades.csv.gz            every fill in the window (maker + taker, role-tagged)
  trades_sample.json       newest 2000 fills (human-readable JSON)
  markets.json             per-condition metadata, category, timing and resolution payouts
  target_profile.json      wallet stats + PnL series (ground truth for validation)
  target_closed_positions.csv  realized PnL per closed position (ground truth)
  collection_meta.json     window, counts, timings
"""
from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd

from api_client import PolymarketAPI
from common import classify_market, iso_to_epoch, save_json, setup_logging, utc

TRADE_COLUMNS = ["timestamp", "side", "condition_id", "token_id", "outcome", "outcome_index",
                 "size", "price", "usdc", "slug", "event_slug", "title", "transaction_hash", "role"]


def _fill_key(t: dict) -> tuple:
    return (t.get("transaction_hash"), t.get("token_id"), t.get("side"), t.get("size"), t.get("price"))


class DataCollector:
    def __init__(self, cfg: dict, api: Optional[PolymarketAPI] = None):
        self.cfg = cfg
        self.api = api or PolymarketAPI(cfg)
        self.wallet = cfg["target"]["wallet"].lower()
        self.ccfg = cfg["collect"]
        self.data_dir = Path(cfg["paths"]["data_dir"])
        self.log = setup_logging(cfg, "collector")

    # ----------------------------------------------------------- window
    def find_activity_window(self) -> tuple[int, int]:
        """Return (anchor_ts, latest_ts). anchor = last time the wallet was *densely* active,
        which ignores isolated late fills (e.g. stale post-resolution fills)."""
        page = self.api.get_trades_page(self.wallet, limit=1000, taker_only=False)
        rows = page.get("data") or []
        if not rows:
            raise RuntimeError("Target wallet has no trades")
        ts = sorted((int(r["timestamp"]) for r in rows), reverse=True)
        latest = ts[0]
        anchor = latest
        for i in range(len(ts) - 20):
            if ts[i] - ts[i + 19] <= 3600:   # >=20 fills within one hour
                anchor = ts[i]
                break
        return anchor, latest

    # ------------------------------------------------------------ trades
    def _fetch_chunk(self, start: int, end: int, taker_only: bool) -> list[dict]:
        keep = set(TRADE_COLUMNS)  # drop profile/icon fields early to keep memory low
        return [{k: v for k, v in r.items() if k in keep}
                for r in self.api.iter_trades(self.wallet, start=start, end=end, taker_only=taker_only)]

    def _fetch_window(self, start: int, end: int, taker_only: bool, label: str) -> list[dict]:
        step = int(self.ccfg.get("chunk_seconds", 3600))
        chunks = []
        e = end
        while e >= start:
            s = max(start, e - step + 1)
            chunks.append((s, e))
            e = s - 1
        rows: list[dict] = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=int(self.ccfg.get("workers", 4))) as pool:
            futs = {pool.submit(self._fetch_chunk, s, e, taker_only): (s, e) for s, e in chunks}
            for n, fut in enumerate(as_completed(futs), 1):
                rows.extend(fut.result())
                if n % 12 == 0 or n == len(chunks):
                    self.log.info("[%s] %d/%d hourly chunks | %d fills | %d req | %.0fs",
                                  label, n, len(chunks), len(rows), self.api.request_count, time.time() - t0)
        return rows

    def collect_trades(self, days: Optional[float], max_trades: Optional[int]) -> tuple[pd.DataFrame, dict]:
        anchor, latest = self.find_activity_window()
        now = int(time.time())
        self.log.info("Wallet last dense activity: %s (latest fill %s, now %s)", utc(anchor), utc(latest), utc(now))
        if now - anchor > 2 * 86400:
            self.log.warning("Target wallet has been INACTIVE for %.1f days - history window is anchored "
                             "to its last active period.", (now - anchor) / 86400)
        end = latest
        start = int(anchor - days * 86400) if days else 1
        include_maker = bool(self.ccfg.get("include_maker_fills", True))

        # dense part of the window is fetched in parallel hourly chunks; the sparse tail
        # after the anchor (isolated late fills) is walked sequentially.
        dense_end = min(end, anchor + 3600)

        def fetch(taker_only: bool, label: str) -> list[dict]:
            if max_trades:
                return list(self.api.iter_trades(self.wallet, start=start, end=end, taker_only=taker_only,
                                                 max_rows=None if label == "taker-only" else max_trades))
            rows = list(self.api.iter_trades(self.wallet, start=dense_end + 1, end=end, taker_only=taker_only)) \
                if end > dense_end else []
            return rows + self._fetch_window(start, dense_end, taker_only=taker_only, label=label)

        if max_trades:
            self.log.info("Collecting newest %d fills (maker=%s) ...", max_trades, include_maker)
            raw = fetch(not include_maker, "all-fills")
            if raw:
                start = min(int(r["timestamp"]) for r in raw)
        else:
            self.log.info("Collecting all fills %s -> %s (maker=%s) ...", utc(start), utc(end), include_maker)
            raw = fetch(not include_maker, "all-fills")

        # role tagging: rows present in the taker-only feed are taker fills
        roles_labeled = False
        if include_maker and self.ccfg.get("label_roles", True) and raw:
            self.log.info("Tagging maker/taker roles via taker-only feed ...")
            taker_rows = fetch(True, "taker-only")
            tk = Counter(_fill_key(t) for t in taker_rows)
            for r in raw:
                k = _fill_key(r)
                if tk.get(k, 0) > 0:
                    r["role"] = "taker"
                    tk[k] -= 1
                else:
                    r["role"] = "maker"
            roles_labeled = True
        else:
            for r in raw:
                r["role"] = "taker" if not include_maker else "unknown"

        df = pd.DataFrame(raw)
        if df.empty:
            raise RuntimeError("No trades collected")
        df["usdc"] = df["size"] * df["price"]
        df = df[[c for c in TRADE_COLUMNS if c in df.columns]]
        df = df.sort_values(["timestamp"], ascending=False, kind="stable").reset_index(drop=True)
        meta = {"anchor_ts": anchor, "anchor_utc": utc(anchor), "latest_ts": latest, "latest_utc": utc(latest),
                "window_start_ts": start, "window_start_utc": utc(start), "window_end_ts": end,
                "window_end_utc": utc(end), "days_inactive": round((now - anchor) / 86400, 1),
                "include_maker_fills": include_maker, "roles_labeled": roles_labeled,
                "n_fills": int(len(df))}
        return df, meta

    # ----------------------------------------------------------- markets
    def collect_markets(self, df: pd.DataFrame) -> dict:
        first = df.drop_duplicates("condition_id")[["condition_id", "slug", "title", "event_slug"]]
        markets: dict[str, dict] = {}
        for row in first.itertuples(index=False):
            info = classify_market(row.slug, row.title)
            markets[row.condition_id] = {"condition_id": row.condition_id, "slug": row.slug, "title": row.title,
                                         "event_slug": row.event_slug, **info}
        cids = list(markets)
        self.log.info("Resolving %d markets (resolutions endpoint, 20/request) ...", len(cids))
        workers = int(self.ccfg.get("workers", 4))

        batches = [cids[i:i + 20] for i in range(0, len(cids), 20)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(self.api.get_resolutions, batches):
                for r in res:
                    m = markets.get(r.get("condition_id"))
                    if m is None:
                        continue
                    m["resolution_status"] = r.get("status")
                    m["payouts"] = r.get("payouts")
                    m["resolved_at"] = iso_to_epoch(r.get("resolved_at"))
                    if m["resolved_at"] is None and str(r.get("last_update_timestamp", "")).isdigit():
                        m["resolved_at"] = float(r["last_update_timestamp"])
        n_res = sum(1 for m in markets.values() if m.get("resolution_status") == "resolved" and m.get("payouts"))
        self.log.info("Resolved markets: %d / %d", n_res, len(cids))

        if self.ccfg.get("enrich_gamma", True):
            self.log.info("Enriching market metadata from gamma API (50/request) ...")
            gbatches = [cids[i:i + 50] for i in range(0, len(cids), 50)]
            found = set()
            for closed in (True, None):
                todo = [b for b in ([c for c in batch if c not in found] for batch in gbatches) if b]
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for res in pool.map(lambda b: self.api.get_gamma_markets(b, closed=closed), todo):
                        for g in res:
                            cid = g.get("conditionId")
                            m = markets.get(cid)
                            if m is None:
                                continue
                            found.add(cid)
                            m["question"] = g.get("question")
                            m["gamma_id"] = g.get("id")
                            m["end_ts"] = iso_to_epoch(g.get("endDate"))
                            m["event_start_ts"] = iso_to_epoch(g.get("eventStartTime"))
                            m["closed"] = g.get("closed")
                            m["uma_status"] = g.get("umaResolutionStatus")
                            try:
                                m["outcome_prices"] = [float(x) for x in json.loads(g.get("outcomePrices") or "[]")]
                            except (TypeError, ValueError):
                                m["outcome_prices"] = None
            self.log.info("Gamma metadata found for %d / %d markets", len(found), len(cids))

        # UMA-resolved markets (e.g. hourly Up/Down) carry no payout vector in /resolutions:
        # fall back to /tokens final prices, then to gamma's settled outcomePrices.
        missing = [c for c, m in markets.items() if not m.get("payouts")]
        if missing:
            self.log.info("Payout fallback via /tokens for %d markets ...", len(missing))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for res in pool.map(lambda b: self.api.get_tokens(condition_ids=b),
                                    [missing[i:i + 10] for i in range(0, len(missing), 10)]):
                    by_cid: dict[str, dict] = {}
                    for t in res:
                        if t.get("resolved") and t.get("final_price") is not None and t.get("outcome_index") in (0, 1):
                            by_cid.setdefault(t["condition_id"], {})[int(t["outcome_index"])] = float(t["final_price"])
                    for cid, px in by_cid.items():
                        if cid in markets and len(px) == 2 and abs(sum(px.values()) - 1) < 1e-6:
                            markets[cid]["payouts"] = [px[0], px[1]]
                            markets[cid]["payout_source"] = "tokens"
            for m in markets.values():
                op = m.get("outcome_prices")
                if not m.get("payouts") and m.get("uma_status") == "resolved" and op and \
                        all(x in (0.0, 1.0) for x in op) and sum(op) == 1:
                    m["payouts"] = op
                    m["payout_source"] = "gamma"
            self.log.info("Markets with payouts after fallback: %d / %d",
                          sum(1 for m in markets.values() if m.get("payouts")), len(markets))

        # trading cutoff for each market: explicit window end > gamma endDate > resolution time
        for m in markets.values():
            m["trade_end_ts"] = m.get("window_end") or m.get("end_ts") or m.get("resolved_at")
            if m.get("window_start") is None and m.get("event_start_ts"):
                m["window_start"] = m["event_start_ts"]
                if m.get("end_ts"):
                    m["window_end"] = m["end_ts"]
        return markets

    # ------------------------------------------------------- ground truth
    def collect_ground_truth(self, start: int, end: int) -> dict:
        self.log.info("Fetching target ground truth (user-stats, PnL series, closed positions) ...")
        stats = self.api.get_user_stats(self.wallet)
        pnl_daily = self.api.get_user_pnl(self.wallet, "all", "1d").get("points", [])
        pnl_hourly = [p for p in self.api.get_user_pnl(self.wallet, "all", "1h").get("points", [])
                      if start - 86400 <= p["timestamp"] <= end + 86400]
        closed = list(self.api.iter_positions(self.wallet, "CLOSED", start=start, end=end + 2 * 86400))
        keep = ["condition_id", "outcome", "outcome_index", "avg_price", "total_size", "realized_pnl",
                "total_pnl", "title", "slug", "first_entry_at", "last_event_at"]
        closed_df = pd.DataFrame(closed)
        if not closed_df.empty:
            closed_df = closed_df[[c for c in keep if c in closed_df.columns]]
            closed_df.to_csv(self.data_dir / "target_closed_positions.csv", index=False)
        self.log.info("Closed positions in window: %d", len(closed_df))
        profile = {"user_stats": stats, "pnl_daily": pnl_daily, "pnl_hourly": pnl_hourly,
                   "n_closed_positions": int(len(closed_df))}
        save_json(profile, self.data_dir / "target_profile.json")
        return profile

    # -------------------------------------------------------------- main
    def refresh_markets(self) -> dict:
        """Re-resolve market metadata for already collected trades (no trade re-download)."""
        df, _, meta = load_collected(self.cfg)
        markets = self.collect_markets(df)
        save_json(markets, self.data_dir / "markets.json")
        meta["n_resolved_markets"] = sum(1 for m in markets.values() if m.get("payouts"))
        save_json(meta, self.data_dir / "collection_meta.json")
        return meta

    def run(self, days: Optional[float] = None, max_trades: Optional[int] = None) -> dict:
        t0 = time.time()
        days = days if days is not None else self.ccfg.get("lookback_days")
        max_trades = max_trades if max_trades is not None else self.ccfg.get("max_trades")
        df, meta = self.collect_trades(days, max_trades)
        trades_path = self.data_dir / "trades.csv.gz"
        df.to_csv(trades_path, index=False, compression="gzip")
        df.head(2000).to_json(self.data_dir / "trades_sample.json", orient="records", indent=1)
        self.log.info("Saved %d fills -> %s", len(df), trades_path)

        markets = self.collect_markets(df)
        save_json(markets, self.data_dir / "markets.json")

        if self.ccfg.get("fetch_ground_truth", True):
            self.collect_ground_truth(meta["window_start_ts"], meta["window_end_ts"])

        meta.update({"n_markets": len(markets),
                     "n_resolved_markets": sum(1 for m in markets.values() if m.get("payouts")),
                     "n_requests": self.api.request_count, "elapsed_seconds": round(time.time() - t0, 1),
                     "collected_at_utc": utc(time.time()), "wallet": self.wallet})
        save_json(meta, self.data_dir / "collection_meta.json")
        self.print_summary(df, meta)
        return meta

    def print_summary(self, df: pd.DataFrame, meta: dict) -> None:
        print("\n" + "=" * 72)
        print(" DATA COLLECTION SUMMARY")
        print("=" * 72)
        print(f" Wallet            : {self.wallet}")
        print(f" Window            : {meta['window_start_utc']}  ->  {meta['window_end_utc']}")
        print(f" Last dense activity: {meta['anchor_utc']}  ({meta['days_inactive']} days ago)")
        print(f" Fills collected   : {meta['n_fills']:,}")
        if meta.get("roles_labeled"):
            rc = df["role"].value_counts()
            print(f" Maker / taker     : {int(rc.get('maker', 0)):,} / {int(rc.get('taker', 0)):,}")
        print(f" Unique markets    : {meta['n_markets']:,}  (resolved: {meta['n_resolved_markets']:,})")
        print(f" USDC volume       : ${df['usdc'].sum():,.0f}")
        print(f" API requests      : {meta['n_requests']:,}  in {meta['elapsed_seconds']}s")
        print("=" * 72 + "\n")


def load_collected(cfg: dict) -> tuple[pd.DataFrame, dict, dict]:
    """Load trades, markets and meta written by DataCollector."""
    from common import load_json
    data_dir = Path(cfg["paths"]["data_dir"])
    path = data_dir / "trades.csv.gz"
    if not path.exists():
        raise FileNotFoundError("No collected data - run `python main.py collect` first")
    df = pd.read_csv(path, dtype={"token_id": str, "condition_id": str})
    markets = load_json(data_dir / "markets.json", {})
    meta = load_json(data_dir / "collection_meta.json", {})
    return df, markets, meta
