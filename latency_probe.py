"""Measure how far Data API v2 trade timestamps trail the real CLOB match time.

Records `last_trade_price` events from the public CLOB market websocket (millisecond match
timestamps) for the live BTC 5m market, then matches them with the Data API rows of the same
market (price + size + outcome).  The resulting delays are used by strategy_backtest.py to move
historical prints back to their true time (otherwise the backtest has look-ahead bias).
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from pathlib import Path

import requests
import websocket

from common import load_config, save_json

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def measure(seconds: int = 180, asset: str = "btc", tf: str = "5m") -> dict:
    s = requests.Session()
    sec = 300 if tf == "5m" else 900
    events: list = []
    conds: dict = {}
    end_at = time.time() + seconds
    while time.time() < end_at:
        now = int(time.time())
        slug = f"{asset}-updown-{tf}-{now - now % sec}"
        m = s.get("https://gamma-api.polymarket.com/markets", params={"slug": slug}, timeout=20).json()
        if not m:
            time.sleep(2)
            continue
        toks = json.loads(m[0]["clobTokenIds"])
        conds[m[0]["conditionId"]] = toks
        run_for = min(end_at, now - now % sec + sec - 2) - time.time()

        def on_open(ws, toks=toks):
            ws.send(json.dumps({"assets_ids": toks, "type": "market"}))

        def on_msg(ws, msg, toks=toks, cid=m[0]["conditionId"]):
            try:
                d = json.loads(msg)
            except ValueError:
                return
            for e in (d if isinstance(d, list) else [d]):
                if e.get("event_type") == "last_trade_price":
                    events.append((cid, toks.index(e["asset_id"]), int(e["timestamp"]) / 1000.0,
                                   float(e["price"]), float(e["size"]), e.get("side")))

        ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_msg)
        th = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": 10}, daemon=True)
        th.start()
        time.sleep(max(run_for, 1))
        ws.close()
    time.sleep(20)  # let the Data API index the last trades
    diffs, side_match = [], 0
    for cid in conds:
        rows = s.get("https://data-api.polymarket.com/v2/trades",
                     params={"condition": cid, "limit": 1000}, timeout=30).json().get("data") or []
        for (c, oi, ts, px, sz, side) in events:
            if c != cid:
                continue
            cand = [r for r in rows if r["outcome_index"] == oi and abs(r["size"] - sz) < 1e-6
                    and abs(r["price"] - px) < 1e-9 and abs(r["timestamp"] - ts) < 15]
            if cand:
                best = min(cand, key=lambda r: abs(r["timestamp"] - ts))
                diffs.append(best["timestamp"] - ts)
                side_match += best["side"] == side
    diffs.sort()
    out = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
           "ws_events": len(events), "matched": len(diffs),
           "taker_side_agrees_pct": 100.0 * side_match / len(diffs) if diffs else None,
           "lag_samples": [round(x, 3) for x in diffs]}
    if diffs:
        out.update(median=statistics.median(diffs), p10=diffs[len(diffs) // 10],
                   p90=diffs[9 * len(diffs) // 10], min=diffs[0], max=diffs[-1])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=180)
    args = ap.parse_args(argv)
    cfg = load_config()
    res = measure(args.seconds)
    save_json(res, Path(cfg["paths"]["data_dir"]) / "tape_lag_measurement.json")
    print({k: v for k, v in res.items() if k != "lag_samples"})


if __name__ == "__main__":
    main()
