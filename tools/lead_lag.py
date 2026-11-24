"""Lead-lag between the fast feed (Binance futures bookTicker), Binance spot and the Polymarket Up-token mid,
from live_paper.py --record files. Answers: how long does Polymarket take to price a futures move?

Usage: python3 tools/lead_lag.py data/recordings/feed_v3_*.jsonl.gz  [--out reports/lead_lag]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import zlib
from collections import defaultdict
from pathlib import Path

import numpy as np

STEP = 0.1                     # grid (s)
LAGS = np.round(np.arange(-2.0, 5.01, 0.25), 2)


def load(paths):
    fast, spot, books, meta = defaultdict(list), defaultdict(list), defaultdict(list), {}
    for p in paths:
        try:
            with gzip.open(p, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    ts, kind = r[0], r[1]
                    if kind == "fast":
                        fast[r[2]].append((ts, np.log(r[3])))
                    elif kind == "spot":
                        spot[r[2]].append((ts, np.log(r[4])))
                    elif kind == "meta":
                        meta[r[2]["slug"]] = r[2]
                    elif kind == "book":
                        top = r[3][0]                      # Up outcome: [bids, asks]
                        if top[0] and top[1]:
                            bb, ba = top[0][0][0], top[1][0][0]
                            if 0.05 <= bb and ba <= 0.95 and ba - bb <= 0.03:
                                books[r[2]].append((ts, (bb + ba) / 2))
        except (EOFError, OSError, zlib.error):
            pass                                           # file still being written / truncated: keep what we read
    return fast, spot, books, meta


def grid(series, t0, t1):
    """Forward-filled values on the STEP grid between t0 and t1 (NaN before the first observation)."""
    s = sorted(series)
    ts = np.array([a for a, _ in s]); vs = np.array([b for _, b in s])
    g = np.arange(t0, t1, STEP)
    idx = np.searchsorted(ts, g, side="right") - 1
    out = np.where(idx >= 0, vs[np.clip(idx, 0, None)], np.nan)
    return g, out


def xcorr(x_diff, y_diff, lags):
    """corr(dx(t), dy(t + lag)) for every lag (positive lag = y moves after x)."""
    out = []
    n = len(x_diff)
    for L in lags:
        k = int(round(L / STEP))
        if k >= 0:
            a, b = x_diff[: n - k], y_diff[k:]
        else:
            a, b = x_diff[-k:], y_diff[: n + k]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 50 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
            out.append(None)
            continue
        out.append(float(np.corrcoef(a[ok], b[ok])[0, 1]))
    return out


def event_study(g, fx, py, thr_bp=2.0, horizons=(0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)):
    """Fast-feed jumps >= thr_bp within 0.5 s: share of the 10-s Polymarket response reached after h seconds."""
    k5 = int(round(0.5 / STEP))
    d = fx[k5:] - fx[:-k5]
    ev = np.where(np.abs(d) >= thr_bp * 1e-4)[0] + k5
    keep, last = [], -10**9
    for e in ev:                                           # one event per 2 s
        if e - last >= int(2 / STEP):
            keep.append(e); last = e
    resp = {h: [] for h in horizons}
    for e in keep:
        sgn = np.sign(fx[e] - fx[e - k5])
        kmax = e + int(round(max(horizons) / STEP))
        if kmax >= len(py) or not np.isfinite(py[e]) or not np.isfinite(py[kmax]):
            continue
        for h in horizons:
            resp[h].append(sgn * (py[e + int(round(h / STEP))] - py[e]))
    n = len(resp[horizons[0]])
    if n == 0:
        return {"events": 0}
    full = float(np.mean(resp[max(horizons)]))
    return {"events": n, "threshold_bp_per_0.5s": thr_bp,
            "mean_move_cents_after": {str(h): round(100 * float(np.mean(v)), 3) for h, v in resp.items()},
            "share_of_10s_move": ({str(h): round(float(np.mean(v)) / full, 3) for h, v in resp.items()}
                                  if abs(full) > 1e-9 else None)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="reports/lead_lag")
    a = ap.parse_args(argv)
    fast, spot, books, meta = load(a.files)
    res = {"files": [Path(f).name for f in a.files], "markets": {}, "spot_vs_fast": {}}
    for asset in fast:
        if len(spot[asset]) < 100 or len(fast[asset]) < 100:
            continue
        t0 = max(fast[asset][0][0], spot[asset][0][0]); t1 = min(fast[asset][-1][0], spot[asset][-1][0])
        g, fx = grid(fast[asset], t0, t1)
        _, sx = grid(spot[asset], t0, t1)
        k = int(round(1.0 / STEP))
        res["spot_vs_fast"][asset] = dict(zip(map(str, LAGS), xcorr(fx[k:] - fx[:-k], sx[k:] - sx[:-k], LAGS)))
    pooled = defaultdict(lambda: defaultdict(list))
    for slug, b in books.items():
        m = meta.get(slug)
        if not m or len(b) < 200 or not fast.get(m["asset"]):
            continue
        t0 = max(b[0][0], fast[m["asset"]][0][0]); t1 = min(b[-1][0], fast[m["asset"]][-1][0], m["window_end"] - 30)
        if t1 - t0 < 60:
            continue
        g, fx = grid(fast[m["asset"]], t0, t1)
        _, py = grid(b, t0, t1)
        k = int(round(0.5 / STEP))
        xc = xcorr(fx[k:] - fx[:-k], py[k:] - py[:-k], LAGS)
        es = event_study(g, fx, py)
        res["markets"][slug] = {"seconds": round(t1 - t0), "xcorr": dict(zip(map(str, LAGS), xc)), "events": es}
        for L, c in zip(LAGS, xc):
            if c is not None:
                pooled[m["category"]][str(L)].append(c)
        if es.get("events"):
            for h, v in es["mean_move_cents_after"].items():
                pooled[m["category"] + " events"][h].append((es["events"], v))
    summary = {}
    for cat, d in pooled.items():
        if cat.endswith(" events"):
            summary[cat] = {h: round(sum(n * v for n, v in xs) / sum(n for n, _ in xs), 3) for h, xs in d.items()}
            summary[cat]["events"] = sum(n for n, _ in next(iter(d.values())))
        else:
            mean = {L: float(np.mean(v)) for L, v in d.items()}
            best = max(mean, key=mean.get)
            summary[cat] = {"peak_lag_s": float(best), "peak_corr": round(mean[best], 3),
                            "corr_at_0": round(mean.get("0.0", float("nan")), 3), "markets": len(next(iter(d.values())))}
    res["summary"] = summary
    for asset, xc in res["spot_vs_fast"].items():
        ok = {L: c for L, c in xc.items() if c is not None}
        if ok:
            best = max(ok, key=ok.get)
            res["summary"][f"{asset} spot vs futures"] = {"peak_lag_s": float(best), "peak_corr": round(ok[best], 3),
                                                          "corr_at_0": round(ok.get("0.0", float("nan")), 3)}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1))
    L = ["# Lead-lag: Binance futures (fast feed) vs Binance spot vs Polymarket Up mid", "",
         f"Recordings: {', '.join(res['files'])}. Grid {STEP} s. Positive lag = the second series moves AFTER the "
         "futures mid.", "",
         "| series | peak lag (s) | corr at peak | corr at lag 0 | n |", "|---|---:|---:|---:|---:|"]
    for k_, v in summary.items():
        if "peak_lag_s" in v:
            L.append(f"| {k_} | {v['peak_lag_s']:+.2f} | {v['peak_corr']:.3f} | {v['corr_at_0']:.3f} | {v.get('markets', '')} |")
    L += ["", "Event study (futures move >= 2 bp within 0.5 s): average Polymarket Up-mid move in the same direction, "
          "cents, h seconds after the move:", "", "| category | events | " +
          " | ".join(f"+{h}s" for h in ("0.25", "0.5", "1.0", "2.0", "3.0", "5.0", "10.0")) + " |",
          "|---|---:|" + "---:|" * 7]
    for k_, v in summary.items():
        if k_.endswith(" events"):
            L.append(f"| {k_[:-7]} | {v['events']} | " + " | ".join(f"{v.get(h, float('nan')):.2f}"
                                                                     for h in ("0.25", "0.5", "1.0", "2.0", "3.0", "5.0", "10.0")) + " |")
    out.with_suffix(".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return res


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
