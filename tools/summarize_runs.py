"""Cumulative summary of many live paper runs (used by the GitHub Actions workflow).

Reads every runs/<run>/live_paper_compare*.json (multi-variant runs) or live_paper_report*.json (single runs)
under the given directory and writes a Markdown summary (Turkish, for the repository owner) to stdout.

    python tools/summarize_runs.py results/runs > results/SUMMARY.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_run(run_dir: Path) -> list:
    comp = sorted(run_dir.glob("live_paper_compare*.json"))
    if comp:
        return json.loads(comp[-1].read_text())
    return [json.loads(p.read_text()) for p in sorted(run_dir.glob("live_paper_report*.json"))]


def main(root: str) -> str:
    runs = sorted(p for p in Path(root).iterdir() if p.is_dir()) if Path(root).exists() else []
    agg: dict = defaultdict(lambda: defaultdict(float))
    cats: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    per_run = []
    for rd in runs:
        try:
            outs = load_run(rd)
        except (OSError, ValueError):
            continue
        if not outs:
            continue
        per_run.append((rd.name, {o.get("variant") or "-": o for o in outs}))
        for o in outs:
            a = agg[o.get("variant") or "-"]
            traded = o.get("markets_traded") or 0
            a["runs"] += 1
            a["settled"] += o.get("markets_settled") or 0
            a["traded"] += traded
            a["wins"] += (o.get("win_rate_pct") or 0.0) * traded / 100.0
            a["pnl"] += o.get("realized_pnl") or 0.0
            a["buy"] += o.get("buy_usdc") or 0.0
            a["maker"] += o.get("maker_fills") or 0
            a["taker"] += o.get("taker_fills") or 0
            a["fees"] += o.get("fees") or 0.0
            a["worst_run"] = min(a.get("worst_run", 0.0), o.get("realized_pnl") or 0.0)
            for c, d in (o.get("by_category") or {}).items():
                for k in ("markets", "pnl", "buy_usdc", "wins"):
                    cats[o.get("variant") or "-"][c][k] += d.get(k) or 0.0

    pct = lambda a, b: f"{100.0 * a / b:+.2f}%" if b else "n/a"  # noqa: E731
    L = ["# Paper test - kümülatif özet", "",
         "Gerçek emir YOK; tüm işlemler canlı Polymarket verisi üzerinde simüle edilir. "
         "Her çalıştırma ~5,5 saat sürer (GitHub Actions).", "",
         f"Toplam çalıştırma: {len(per_run)}", "",
         "## Varyantlar (tüm çalıştırmalar toplamı)", "",
         "| varyant | çalıştırma | işlem yapılan market | toplam PnL | PnL / alım | kazanma | alım | maker / taker | ücret | en kötü çalıştırma |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["pnl"]):
        L.append(f"| {name} | {int(a['runs'])} | {int(a['traded'])} | ${a['pnl']:+,.2f} | {pct(a['pnl'], a['buy'])} | "
                 f"{(100.0 * a['wins'] / a['traded']) if a['traded'] else 0:.1f}% | ${a['buy']:,.0f} | "
                 f"{int(a['maker'])} / {int(a['taker'])} | ${a['fees']:,.2f} | ${a['worst_run']:+,.2f} |")
    L += ["", "Hedef cüzdan referansı: PnL / alım +%1,71, kazanma %50,6.", "",
          "## Varyant x kategori", "", "| varyant | kategori | market | PnL | PnL / alım | kazanma |",
          "|---|---|---:|---:|---:|---:|"]
    for name in sorted(cats):
        for c, d in sorted(cats[name].items()):
            L.append(f"| {name} | {c} | {int(d['markets'])} | ${d['pnl']:+,.2f} | {pct(d['pnl'], d['buy_usdc'])} | "
                     f"{(100.0 * d['wins'] / d['markets']) if d['markets'] else 0:.1f}% |")
    names = sorted(agg)
    L += ["", "## Çalıştırma bazında PnL", "", "| çalıştırma | " + " | ".join(names) + " |",
          "|---|" + "---:|" * len(names)]
    for run, outs in reversed(per_run):
        L.append(f"| {run} | " + " | ".join(
            f"${outs[n]['realized_pnl']:+,.2f}" if n in outs else "-" for n in names) + " |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.stdout.write(main(sys.argv[1] if len(sys.argv) > 1 else "results/runs"))
