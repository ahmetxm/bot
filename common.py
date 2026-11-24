"""Shared helpers: config loading, logging, market classification, fees, JSON IO."""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent

UPDOWN_RE = re.compile(r"^(?P<asset>[a-z]+)-updown-(?P<tf>\d+m|\d+h)-(?P<epoch>\d{9,11})$")
ASSET_ALIASES = {
    "btc": "BTC", "bitcoin": "BTC",
    "eth": "ETH", "ethereum": "ETH",
    "sol": "SOL", "solana": "SOL",
    "xrp": "XRP",
    "doge": "DOGE", "dogecoin": "DOGE",
    "bnb": "BNB",
}
TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def load_config(path: Optional[str] = None) -> dict:
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    for key in ("data_dir", "reports_dir", "logs_dir"):
        p = Path(cfg["paths"][key])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        cfg["paths"][key] = str(p)
    return cfg


def setup_logging(cfg: dict, name: str, level: int = logging.INFO) -> logging.Logger:
    """Console + file logging (logs/<name>.log)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    Path(cfg["paths"]["logs_dir"]).mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(Path(cfg["paths"]["logs_dir"]) / f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(fh)
    logger.propagate = False
    return logger


def utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def iso_to_epoch(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T")
        if s.endswith("+00"):
            s += ":00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def classify_market(slug: str, title: str = "") -> dict:
    """Return asset / timeframe / window info for a market slug."""
    slug = (slug or "").lower()
    title_l = (title or "").lower()
    m = UPDOWN_RE.match(slug)
    if m:
        asset = ASSET_ALIASES.get(m.group("asset"), m.group("asset").upper())
        tf = m.group("tf")
        start = int(m.group("epoch"))
        dur = TF_SECONDS.get(tf)
        return {"asset": asset, "timeframe": tf, "window_start": start,
                "window_end": start + dur if dur else None, "category": f"{asset} {tf}"}
    asset = "OTHER"
    for k, v in ASSET_ALIASES.items():
        if slug.startswith(k + "-") or title_l.startswith(k + " "):
            asset = v
            break
    if "up-or-down" in slug:
        # hourly markets: bitcoin-up-or-down-march-24-2026-8am-et
        tf = "1h" if re.search(r"-\d{1,2}(am|pm)-et$", slug) else "1d"
    elif asset != "OTHER":
        tf = "other"
    else:
        tf = "other"
    cat = f"{asset} {tf}" if asset != "OTHER" else "Other"
    return {"asset": asset, "timeframe": tf, "window_start": None, "window_end": None, "category": cat}


def taker_fee(shares: float, price: float, category: str, fees_cfg: dict) -> float:
    """Polymarket taker fee: shares * rate * p * (1-p)."""
    asset, _, tf = category.partition(" ")
    if asset == "BTC" and tf in ("5m", "15m"):
        rate = fees_cfg.get("btc_updown_short_rate", 0.0)
    elif asset in ASSET_ALIASES.values():
        rate = fees_cfg.get("crypto_other_rate", 0.0)
    else:
        rate = fees_cfg.get("default_rate", 0.0)
    fee = shares * rate * price * (1.0 - price)
    return round(fee, 5) if fee >= 1e-5 else 0.0


def payout_per_share(payouts: Optional[list], outcome_index: int) -> Optional[float]:
    if not payouts:
        return None
    try:
        tot = float(sum(float(x) for x in payouts))
        if tot <= 0 or outcome_index >= len(payouts):
            return None
        return float(payouts[outcome_index]) / tot
    except (TypeError, ValueError):
        return None


def _sanitize(o: Any) -> Any:
    """Convert numpy scalars / NaN / inf into strict-JSON friendly values."""
    if isinstance(o, dict):
        return {str(k): _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except (ValueError, AttributeError):
            return str(o)
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def save_json(obj: Any, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_sanitize(obj), fh, indent=2, default=str)


def load_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def env_secret(name: str) -> Optional[str]:
    val = os.environ.get(name)
    return val.strip() if val else None
