"""Strategy analysis of the target wallet's trade history.

Writes reports/strategy_analysis.json, reports/strategy_analysis.md and charts in reports/charts/.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import load_json, payout_per_share, save_json, setup_logging, utc  # noqa: E402
from data_collector import load_collected  # noqa: E402


def describe(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    return {"count": int(s.size), "mean": float(s.mean()), "median": float(s.median()), "std": float(s.std()),
            "min": float(s.min()), "p10": float(s.quantile(.10)), "p90": float(s.quantile(.90)),
            "p99": float(s.quantile(.99)), "max": float(s.max()), "sum": float(s.sum())}


def prepare_trades(df: pd.DataFrame, markets: dict) -> pd.DataFrame:
    """Join market metadata, compute signed flows and flag fills after a market's trading cutoff."""
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    mk = pd.DataFrame.from_dict(markets, orient="index")
    cols = ["category", "asset", "timeframe", "window_start", "window_end", "trade_end_ts", "resolved_at"]
    for c in cols:
        if c not in mk.columns:
            mk[c] = np.nan
    df = df.join(mk[cols], on="condition_id")
    df["category"] = df["category"].fillna("Other")
    df["sign"] = np.where(df["side"] == "BUY", 1.0, -1.0)
    df["signed_shares"] = df["sign"] * df["size"]
    df["cash_flow"] = -df["signed_shares"] * df["price"]
    pay = {cid: m.get("payouts") for cid, m in markets.items()}
    idx = df["outcome_index"].astype(int).to_numpy()
    df["payout"] = [payout_per_share(pay.get(c), i) for c, i in zip(df["condition_id"].to_numpy(), idx)]
    df["post_close"] = df["trade_end_ts"].notna() & (df["timestamp"] > df["trade_end_ts"] + 60)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


def market_pnl(df: pd.DataFrame) -> pd.DataFrame:
    """Per-market PnL = sell proceeds - buy cost + sum_i(net_shares_i * payout_i).
    Valid with split/merge activity too, since a full set of outcomes is always worth $1."""
    g = df.groupby(["condition_id", "outcome_index"]).agg(net=("signed_shares", "sum"), cash=("cash_flow", "sum"),
                                                         payout=("payout", "first"))
    g["value"] = g["net"] * g["payout"]
    m = g.groupby(level=0).agg(cash=("cash", "sum"), value=("value", "sum"),
                               resolved=("payout", lambda s: s.notna().all()))
    m["pnl"] = m["cash"] + m["value"]
    tmp = df.assign(buy_usdc=np.where(df["side"] == "BUY", df["usdc"], 0.0))
    info = tmp.groupby("condition_id").agg(category=("category", "first"), first_ts=("timestamp", "min"),
                                           last_ts=("timestamp", "max"), fills=("size", "size"),
                                           buy_usdc=("buy_usdc", "sum"), volume_usdc=("usdc", "sum"))
    return m.join(info)


class StrategyAnalyzer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log = setup_logging(cfg, "analyzer")
        self.reports = Path(cfg["paths"]["reports_dir"])
        self.charts = self.reports / "charts"
        self.charts.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        raw, markets, meta = load_collected(self.cfg)
        profile = load_json(Path(self.cfg["paths"]["data_dir"]) / "target_profile.json", {})
        self.log.info("Loaded %d fills, %d markets", len(raw), len(markets))
        df_all = prepare_trades(raw, markets)
        n_post = int(df_all["post_close"].sum())
        df = df_all[~df_all["post_close"]].copy()
        res: dict = {"meta": meta, "data_quality": {"fills_total": int(len(df_all)),
                                                    "fills_after_market_close_excluded": n_post}}
        res["overview"] = self._overview(df)
        res["market_focus"] = self._market_focus(df)
        res["side_distribution"] = self._sides(df)
        res["position_sizes"] = self._sizes(df)
        res["frequency"] = self._frequency(df)
        res["entry_timing"] = self._entry_timing(df)
        res["price_profile"] = self._prices(df)
        res["two_sided_behaviour"] = self._two_sided(df)
        perf, mp = self._performance(df, meta)
        res["performance"] = perf
        res["ground_truth"] = self._ground_truth(profile, meta)
        res["strategy_summary"] = self._summary(res)
        self._charts(df, mp, res)
        save_json(res, self.reports / "strategy_analysis.json")
        mp.to_csv(self.reports / "target_market_pnl.csv")
        self._write_markdown(res)
        self._print(res)
        return res

    # --------------------------------------------------------- sections
    def _overview(self, df: pd.DataFrame) -> dict:
        days = max((df.timestamp.max() - df.timestamp.min()) / 86400, 1e-9)
        roles = df.groupby("role").agg(fills=("size", "size"), usdc=("usdc", "sum"))
        return {"first_fill_utc": utc(df.timestamp.min()), "last_fill_utc": utc(df.timestamp.max()),
                "span_days": round(days, 2), "fills": int(len(df)), "markets": int(df.condition_id.nunique()),
                "volume_usdc": float(df.usdc.sum()), "fills_per_day": float(len(df) / days),
                "volume_per_day_usdc": float(df.usdc.sum() / days),
                "markets_per_day": float(df.condition_id.nunique() / days),
                "roles": {r: {"fills": int(v.fills), "fills_pct": float(v.fills / len(df) * 100),
                              "usdc": float(v.usdc), "usdc_pct": float(v.usdc / df.usdc.sum() * 100)}
                          for r, v in roles.iterrows()}}

    def _market_focus(self, df: pd.DataFrame) -> dict:
        tot = df.usdc.sum()
        out = {}
        for col in ("category", "asset", "timeframe"):
            g = df.groupby(col).agg(fills=("size", "size"), usdc=("usdc", "sum"), markets=("condition_id", "nunique"))
            g["usdc_pct"] = g.usdc / tot * 100
            g["fills_pct"] = g.fills / len(df) * 100
            out[f"by_{col}"] = g.sort_values("usdc", ascending=False).round(3).to_dict(orient="index")
        btc_short = df[(df.asset == "BTC") & df.timeframe.isin(["5m", "15m"])]
        out["btc_5m_15m_usdc_pct"] = float(btc_short.usdc.sum() / tot * 100)
        out["btc_5m_15m_fills_pct"] = float(len(btc_short) / len(df) * 100)
        updown = df[df.timeframe.isin(["5m", "15m", "1h"])]
        out["crypto_updown_usdc_pct"] = float(updown.usdc.sum() / tot * 100)
        return out

    def _sides(self, df: pd.DataFrame) -> dict:
        g = df.groupby(["side"]).agg(fills=("size", "size"), usdc=("usdc", "sum"), shares=("size", "sum"))
        g2 = df.groupby(["role", "side"]).agg(fills=("size", "size"), usdc=("usdc", "sum"))
        oc = df.groupby("outcome").agg(fills=("size", "size"), usdc=("usdc", "sum"))
        return {"by_side": g.round(2).to_dict(orient="index"),
                "by_role_side": {f"{a}/{b}": v for (a, b), v in g2.round(2).to_dict(orient="index").items()},
                "by_outcome": oc.round(2).to_dict(orient="index"),
                "buy_fill_pct": float((df.side == "BUY").mean() * 100)}

    def _sizes(self, df: pd.DataFrame) -> dict:
        per_mkt = df[df.side == "BUY"].groupby("condition_id").usdc.sum()
        return {"fill_usdc": describe(df.usdc), "fill_shares": describe(df["size"]),
                "buy_fill_usdc": describe(df[df.side == "BUY"].usdc),
                "per_market_buy_usdc": describe(per_mkt),
                "per_market_fills": describe(df.groupby("condition_id").size().astype(float))}

    def _frequency(self, df: pd.DataFrame) -> dict:
        d = df.set_index("dt")
        daily = d.resample("1D").agg({"size": "size", "usdc": "sum", "condition_id": "nunique"})
        daily.columns = ["fills", "usdc", "markets"]
        hours = df.groupby(df.dt.dt.hour).agg(fills=("size", "size"), usdc=("usdc", "sum"))
        ndays = max(df.dt.dt.normalize().nunique(), 1)
        hours["fills_per_day"] = hours.fills / ndays
        dow = df.groupby(df.dt.dt.day_name()).agg(fills=("size", "size"), usdc=("usdc", "sum"))
        top = hours.sort_values("usdc", ascending=False).head(5).index.tolist()
        low = hours.sort_values("usdc").head(3).index.tolist()
        return {"daily": {str(k.date()): v for k, v in daily.round(2).to_dict(orient="index").items()},
                "hour_of_day_utc": {int(k): v for k, v in hours.round(2).to_dict(orient="index").items()},
                "day_of_week": dow.round(2).to_dict(orient="index"),
                "most_active_hours_utc": [int(h) for h in top], "least_active_hours_utc": [int(h) for h in low],
                "hourly_fill_rate": describe(d.resample("1h").size().astype(float))}

    def _entry_timing(self, df: pd.DataFrame) -> dict:
        w = df[df.window_start.notna() & df.window_end.notna()].copy()
        if w.empty:
            return {}
        dur = (w.window_end - w.window_start).clip(lower=1)
        w["frac"] = (w.timestamp - w.window_start) / dur
        w["secs_to_end"] = w.window_end - w.timestamp
        bins = [-np.inf, 0, .2, .4, .6, .8, .9, 1.0, np.inf]
        labels = ["before window", "0-20%", "20-40%", "40-60%", "60-80%", "80-90%", "90-100%", "after end"]
        w["bucket"] = pd.cut(w.frac, bins=bins, labels=labels, right=False)
        g = w.groupby("bucket", observed=False).agg(fills=("size", "size"), usdc=("usdc", "sum"))
        g["usdc_pct"] = g.usdc / g.usdc.sum() * 100
        out = {"by_window_fraction": g.round(3).to_dict(orient="index"),
               "median_window_fraction": float(w.frac.median())}
        for tf in ("5m", "15m"):
            x = w[w.timeframe == tf]
            if len(x):
                out[f"{tf}_seconds_to_window_end"] = describe(x.secs_to_end.astype(float))
                out[f"{tf}_seconds_from_window_start"] = describe((x.timestamp - x.window_start).astype(float))
        return out

    def _prices(self, df: pd.DataFrame) -> dict:
        b = df[df.side == "BUY"].copy()
        bins = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, 1.0001]
        b["bucket"] = pd.cut(b.price, bins=bins, right=False)
        g = b.groupby("bucket", observed=False).agg(fills=("size", "size"), usdc=("usdc", "sum"))
        g["usdc_pct"] = g.usdc / g.usdc.sum() * 100
        vw = float((b.price * b["size"]).sum() / b["size"].sum()) if len(b) else None
        return {"buy_price_buckets": {str(k): v for k, v in g.round(3).to_dict(orient="index").items()},
                "buy_vwap_price": vw, "buy_price": describe(b.price)}

    def _two_sided(self, df: pd.DataFrame) -> dict:
        b = df[(df.side == "BUY") & df.outcome_index.isin([0, 1])]
        g = b.groupby(["condition_id", "outcome_index"]).agg(sh=("size", "sum"), usdc=("usdc", "sum"))
        g["avg"] = g.usdc / g.sh
        piv = g.unstack("outcome_index")
        both = piv.dropna(subset=[("sh", 0), ("sh", 1)])
        n = int(piv.shape[0])
        if both.empty:
            return {"markets_with_buys": n, "both_sides_pct": 0.0}
        pair_cost = both[("avg", 0)] + both[("avg", 1)]
        balance = np.minimum(both[("sh", 0)], both[("sh", 1)]) / np.maximum(both[("sh", 0)], both[("sh", 1)])
        sells = df[df.side == "SELL"]
        return {"markets_with_buys": n, "markets_buying_both_outcomes": int(len(both)),
                "both_sides_pct": float(len(both) / n * 100),
                "avg_combined_cost_up_plus_down": float(pair_cost.mean()),
                "median_combined_cost_up_plus_down": float(pair_cost.median()),
                "pct_pairs_combined_cost_below_1": float((pair_cost < 1).mean() * 100),
                "median_share_balance_ratio": float(balance.median()),
                "sell_fills_pct": float(len(sells) / len(df) * 100)}

    def _performance(self, df: pd.DataFrame, meta: dict) -> tuple[dict, pd.DataFrame]:
        mp = market_pnl(df)
        buffer = float(self.cfg["strategy"].get("truncation_buffer_seconds", 3600))
        data_start = df.timestamp.min()
        mp["truncated"] = mp.first_ts < data_start + buffer
        ok = mp[mp.resolved & ~mp.truncated]
        out = {"markets_total": int(len(mp)), "markets_resolved": int(mp.resolved.sum()),
               "markets_truncated_excluded": int(mp.truncated.sum()), "markets_evaluated": int(len(ok))}
        if ok.empty:
            return out, mp
        wins = ok[ok.pnl > 0]
        losses = ok[ok.pnl < 0]
        out.update({"total_pnl_usdc": float(ok.pnl.sum()), "win_rate_pct": float(len(wins) / len(ok) * 100),
                    "loss_rate_pct": float(len(losses) / len(ok) * 100),
                    "avg_win": float(wins.pnl.mean()) if len(wins) else 0.0,
                    "avg_loss": float(losses.pnl.mean()) if len(losses) else 0.0,
                    "profit_factor": float(wins.pnl.sum() / -losses.pnl.sum()) if len(losses) else None,
                    "roi_on_buy_volume_pct": float(ok.pnl.sum() / ok.buy_usdc.sum() * 100),
                    "market_pnl_distribution": describe(ok.pnl)})
        bc = ok.groupby("category").agg(markets=("pnl", "size"), pnl=("pnl", "sum"),
                                        win_rate=("pnl", lambda s: (s > 0).mean() * 100),
                                        buy_usdc=("buy_usdc", "sum"))
        bc["roi_pct"] = bc.pnl / bc.buy_usdc * 100
        out["by_category"] = bc.sort_values("pnl", ascending=False).round(3).to_dict(orient="index")
        ok_dt = pd.to_datetime(ok.last_ts, unit="s", utc=True)
        daily = ok.groupby(ok_dt.dt.date).pnl.agg(["sum", "size", lambda s: (s > 0).mean() * 100])
        daily.columns = ["pnl", "markets", "win_rate"]
        out["daily_pnl"] = {str(k): v for k, v in daily.round(2).to_dict(orient="index").items()}
        hourly = ok.groupby(ok_dt.dt.hour).pnl.agg(["sum", "size"])
        out["pnl_by_hour_utc"] = {int(k): {"pnl": round(float(v["sum"]), 2), "markets": int(v["size"])}
                                  for k, v in hourly.iterrows()}
        # directional accuracy / calibration of BUY fills
        b = df[(df.side == "BUY") & df.payout.notna() & df.condition_id.isin(ok.index)].copy()
        b["won"] = (b.payout > 0.5).astype(float)
        bins = [0, .2, .4, .5, .6, .8, .95, 1.0001]
        b["bucket"] = pd.cut(b.price, bins=bins, right=False)
        cal = b.groupby("bucket", observed=False).apply(
            lambda x: pd.Series({"fills": len(x), "usdc": x.usdc.sum(),
                                 "avg_price": np.average(x.price, weights=x["size"]) if len(x) else np.nan,
                                 "win_rate": np.average(x.won, weights=x["size"]) if len(x) else np.nan}),
            include_groups=False)
        cal["edge_pct_pts"] = (cal.win_rate - cal.avg_price) * 100
        out["buy_fill_win_rate_pct"] = float(b.won.mean() * 100) if len(b) else None
        out["buy_fill_win_rate_share_weighted_pct"] = float(np.average(b.won, weights=b["size"]) * 100) if len(b) else None
        out["buy_calibration"] = {str(k): v for k, v in cal.round(4).to_dict(orient="index").items()}
        for role in ("maker", "taker"):
            r = b[b.role == role]
            if len(r):
                out[f"buy_{role}_win_rate_share_weighted_pct"] = float(np.average(r.won, weights=r["size"]) * 100)
                out[f"buy_{role}_avg_price"] = float(np.average(r.price, weights=r["size"]))
        return out, mp

    def _ground_truth(self, profile: dict, meta: dict) -> dict:
        if not profile:
            return {}
        st = profile.get("user_stats", {})
        at = st.get("all_time_pnl", {}) or {}
        out = {"all_time": {"trades": st.get("trades"), "trade_count": at.get("trade_count"),
                            "economic_pnl": at.get("economic_pnl"), "trade_pnl": at.get("trade_pnl"),
                            "realized_pnl": at.get("realized_pnl"), "volume_usdc": at.get("volume_usdc"),
                            "fees_paid": at.get("fees_paid"), "maker_rebate": at.get("maker_rebate"),
                            "join_date_utc": utc(st["join_date"]) if st.get("join_date") else None,
                            "biggest_win": st.get("biggest_win")}}
        pts = [p for p in profile.get("pnl_hourly", [])
               if meta.get("window_start_ts", 0) <= p["timestamp"] <= meta.get("window_end_ts", 0) + 3600]
        if len(pts) >= 2:
            a, b = pts[0], pts[-1]
            out["window"] = {"from_utc": utc(a["timestamp"]), "to_utc": utc(b["timestamp"]),
                             **{k: (b.get(k) or 0) - (a.get(k) or 0) for k in
                                ("economic_pnl", "trade_pnl", "realized_pnl", "volume_usdc", "fees", "maker_rebate")}}
        daily = profile.get("pnl_daily", [])
        if daily:
            rows = []
            for prev, cur in zip(daily, daily[1:]):
                rows.append({"date": utc(cur["timestamp"])[:10],
                             "pnl": (cur.get("economic_pnl") or 0) - (prev.get("economic_pnl") or 0)})
            act = [r for r in rows if abs(r["pnl"]) > 1]
            if act:
                vals = np.array([r["pnl"] for r in act])
                out["daily_economic_pnl_all_time"] = {"active_days": len(act), "positive_days_pct":
                                                      float((vals > 0).mean() * 100), "mean": float(vals.mean()),
                                                      "median": float(np.median(vals)), "min": float(vals.min()),
                                                      "max": float(vals.max()),
                                                      "first_active": act[0]["date"], "last_active": act[-1]["date"]}
        return out

    def _summary(self, r: dict) -> list[str]:
        s = []
        ov, mf, ts, sz = r["overview"], r["market_focus"], r["two_sided_behaviour"], r["position_sizes"]
        roles = ov.get("roles", {})
        if "maker" in roles:
            s.append(f"Liquidity role: {roles['maker']['fills_pct']:.1f}% of fills / {roles['maker']['usdc_pct']:.1f}% of "
                     f"USDC volume are MAKER (passive limit orders) - the wallet is primarily a market maker.")
        s.append(f"Market focus: BTC 5m+15m Up/Down = {mf['btc_5m_15m_usdc_pct']:.1f}% of USDC volume; "
                 f"all crypto Up/Down (5m/15m/1h) = {mf['crypto_updown_usdc_pct']:.1f}%.")
        s.append(f"Activity: {ov['fills_per_day']:,.0f} fills/day across {ov['markets_per_day']:,.0f} markets/day; "
                 f"${ov['volume_per_day_usdc']:,.0f} USDC/day.")
        if sz.get("fill_usdc"):
            s.append(f"Sizing: median fill ${sz['fill_usdc']['median']:.2f}, mean ${sz['fill_usdc']['mean']:.2f}; "
                     f"median per-market buy volume ${sz['per_market_buy_usdc']['median']:,.0f}.")
        if ts.get("both_sides_pct") is not None:
            s.append(f"Two-sided: buys BOTH Up and Down in {ts['both_sides_pct']:.1f}% of markets "
                     f"(median combined cost {ts.get('median_combined_cost_up_plus_down', float('nan')):.3f}).")
        p = r["performance"]
        if p.get("win_rate_pct") is not None:
            s.append(f"Results (evaluated markets): win rate {p['win_rate_pct']:.1f}%, PnL ${p['total_pnl_usdc']:,.0f}, "
                     f"ROI on buy volume {p['roi_on_buy_volume_pct']:.2f}%.")
        gt = r.get("ground_truth", {}).get("all_time", {})
        if gt.get("economic_pnl") is not None:
            s.append(f"Ground truth (Polymarket): all-time economic PnL ${gt['economic_pnl']:,.0f}, "
                     f"volume ${gt['volume_usdc']:,.0f}.")
        if r["meta"].get("days_inactive", 0) > 2:
            s.append(f"WARNING: the wallet has been inactive for {r['meta']['days_inactive']} days "
                     f"(last dense activity {r['meta']['anchor_utc']}). A live copy bot would currently receive no signals.")
        return s

    # ------------------------------------------------------------ output
    def _charts(self, df: pd.DataFrame, mp: pd.DataFrame, r: dict) -> None:
        try:
            fig, ax = plt.subplots(1, 2, figsize=(13, 4))
            h = pd.DataFrame(r["frequency"]["hour_of_day_utc"]).T
            ax[0].bar(h.index, h["usdc"] / 1000, color="#3b82f6")
            ax[0].set_title("USDC volume by hour of day (UTC), $k")
            ax[0].set_xlabel("hour")
            cat = pd.DataFrame(r["market_focus"]["by_category"]).T.head(10)
            ax[1].barh(cat.index[::-1], cat["usdc_pct"][::-1], color="#10b981")
            ax[1].set_title("Share of USDC volume by market category (%)")
            fig.tight_layout()
            fig.savefig(self.charts / "activity_and_focus.png", dpi=110)
            plt.close(fig)

            ok = mp[mp.resolved & ~mp.truncated]
            if len(ok):
                fig, ax = plt.subplots(1, 2, figsize=(13, 4))
                clip = ok.pnl.clip(ok.pnl.quantile(.01), ok.pnl.quantile(.99))
                ax[0].hist(clip, bins=80, color="#6366f1")
                ax[0].axvline(0, color="k", lw=.8)
                ax[0].set_title("Per-market PnL distribution (1-99 pct), USDC")
                d = pd.DataFrame(r["performance"]["daily_pnl"]).T
                ax[1].bar(d.index, d["pnl"], color=["#16a34a" if v > 0 else "#dc2626" for v in d["pnl"]])
                ax[1].set_title("Daily PnL reconstructed from fills, USDC")
                ax[1].tick_params(axis="x", rotation=45)
                fig.tight_layout()
                fig.savefig(self.charts / "pnl_distribution.png", dpi=110)
                plt.close(fig)
            et = r.get("entry_timing", {}).get("by_window_fraction")
            cal = r["performance"].get("buy_calibration")
            if et and cal:
                fig, ax = plt.subplots(1, 2, figsize=(13, 4))
                e = pd.DataFrame(et).T
                ax[0].bar(e.index, e["usdc_pct"], color="#f59e0b")
                ax[0].set_title("When in the market window volume is traded (%)")
                ax[0].tick_params(axis="x", rotation=30)
                c = pd.DataFrame(cal).T.dropna()
                ax[1].plot([0, 1], [0, 1], "k--", lw=.8, label="break-even")
                ax[1].scatter(c["avg_price"], c["win_rate"], s=np.sqrt(c["usdc"].astype(float)) * 2, color="#ef4444")
                ax[1].set_xlabel("avg BUY price")
                ax[1].set_ylabel("realized win frequency")
                ax[1].set_title("BUY calibration: above the line = edge")
                ax[1].legend()
                fig.tight_layout()
                fig.savefig(self.charts / "timing_and_calibration.png", dpi=110)
                plt.close(fig)
        except Exception as exc:  # charts are best-effort
            self.log.warning("chart generation failed: %s", exc)

    def _write_markdown(self, r: dict) -> None:
        ov, p = r["overview"], r["performance"]
        lines = ["# Strategy analysis - target wallet", "",
                 f"Wallet `{r['meta'].get('wallet')}` | data window {ov['first_fill_utc']} -> {ov['last_fill_utc']} "
                 f"({ov['span_days']} days, {ov['fills']:,} fills, {ov['markets']:,} markets)", "",
                 "## Key findings", ""] + [f"- {x}" for x in r["strategy_summary"]] + ["", "## Market focus (USDC share)", "",
                                                                                     "| category | fills | USDC | share % |", "|---|---:|---:|---:|"]
        for k, v in list(r["market_focus"]["by_category"].items())[:12]:
            lines.append(f"| {k} | {v['fills']:,} | ${v['usdc']:,.0f} | {v['usdc_pct']:.2f} |")
        if p.get("by_category"):
            lines += ["", "## Performance by category (resolved, non-truncated markets)", "",
                      "| category | markets | PnL | win rate % | ROI % |", "|---|---:|---:|---:|---:|"]
            for k, v in p["by_category"].items():
                lines.append(f"| {k} | {int(v['markets']):,} | ${v['pnl']:,.0f} | {v['win_rate']:.1f} | {v['roi_pct']:.2f} |")
        lines += ["", "Charts: `charts/activity_and_focus.png`, `charts/pnl_distribution.png`, "
                      "`charts/timing_and_calibration.png`. Full numbers: `strategy_analysis.json`."]
        (self.reports / "strategy_analysis.md").write_text("\n".join(lines), encoding="utf-8")

    def _print(self, r: dict) -> None:
        ov, mf, sd, sz, fr, p = (r["overview"], r["market_focus"], r["side_distribution"], r["position_sizes"],
                                 r["frequency"], r["performance"])
        bar = "=" * 72
        print(f"\n{bar}\n STRATEGY ANALYSIS - {r['meta'].get('wallet')}\n{bar}")
        print(f" Window      : {ov['first_fill_utc']} -> {ov['last_fill_utc']} ({ov['span_days']} d)")
        print(f" Fills       : {ov['fills']:,}  | markets {ov['markets']:,} | volume ${ov['volume_usdc']:,.0f}")
        print(f" Excluded    : {r['data_quality']['fills_after_market_close_excluded']} fills after market close")
        for role, v in ov.get("roles", {}).items():
            print(f" Role {role:<6} : {v['fills_pct']:5.1f}% of fills | {v['usdc_pct']:5.1f}% of USDC")
        print(f"\n -- Market focus (USDC share) --")
        for k, v in list(mf["by_category"].items())[:8]:
            print(f"   {k:<12} {v['usdc_pct']:6.2f}%  fills {v['fills']:>8,}  markets {v['markets']:>5,}")
        print(f"   BTC 5m+15m total: {mf['btc_5m_15m_usdc_pct']:.1f}% of volume")
        print(f"\n -- Buy / Sell --")
        for k, v in sd["by_side"].items():
            print(f"   {k:<4} fills {v['fills']:>8,}  USDC ${v['usdc']:>13,.0f}")
        print(f"\n -- Position sizes (USDC per fill) --")
        f = sz["fill_usdc"]
        print(f"   mean ${f['mean']:.2f} | median ${f['median']:.2f} | min ${f['min']:.4f} | max ${f['max']:,.2f} | p99 ${f['p99']:,.2f}")
        m = sz["per_market_buy_usdc"]
        print(f"   per market buy volume: mean ${m['mean']:,.0f} | median ${m['median']:,.0f} | max ${m['max']:,.0f}")
        print(f"\n -- Frequency --")
        print(f"   {ov['fills_per_day']:,.0f} fills/day | {ov['markets_per_day']:,.0f} markets/day")
        print(f"   most active hours (UTC): {fr['most_active_hours_utc']} | least active: {fr['least_active_hours_utc']}")
        et = r.get("entry_timing", {})
        if et:
            print(f"   median position in market window: {et['median_window_fraction']*100:.0f}% of the window elapsed")
        ts = r["two_sided_behaviour"]
        print(f"   buys both outcomes in {ts.get('both_sides_pct', 0):.1f}% of markets")
        print(f"\n -- Performance (resolved, non-truncated markets: {p.get('markets_evaluated', 0):,}) --")
        if p.get("win_rate_pct") is not None:
            print(f"   PnL ${p['total_pnl_usdc']:,.2f} | win rate {p['win_rate_pct']:.2f}% | profit factor "
                  f"{p['profit_factor']:.3f} | ROI on buys {p['roi_on_buy_volume_pct']:.2f}%")
            print(f"   avg win ${p['avg_win']:,.2f} | avg loss ${p['avg_loss']:,.2f}")
            print(f"   BUY-fill win rate (share weighted): {p['buy_fill_win_rate_share_weighted_pct']:.2f}%")
        gt = r.get("ground_truth", {})
        if gt.get("window"):
            w = gt["window"]
            print(f"   Ground truth window PnL (Polymarket user-pnl): economic ${w['economic_pnl']:,.0f} | "
                  f"trade ${w['trade_pnl']:,.0f}")
        print(f"\n -- Strategy summary --")
        for line in r["strategy_summary"]:
            print(f"   * {line}")
        print(f"{bar}\n Saved: reports/strategy_analysis.json, strategy_analysis.md, charts/\n{bar}\n")
