"""Thin, rate-limited REST client for the public Polymarket APIs (no SDK, no auth).

Endpoints used
  Data API v2 : /trades, /resolutions, /tokens, /positions, /user-pnl, /user-stats
  Gamma API   : /markets
  CLOB API    : /midpoint, /price
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Iterator, Optional

import requests

log = logging.getLogger("api")


class PolymarketAPI:
    def __init__(self, cfg: dict):
        api = cfg["api"]
        self.data_api = api["data_api"].rstrip("/")
        self.gamma_api = api["gamma_api"].rstrip("/")
        self.clob_api = api["clob_api"].rstrip("/")
        self.timeout = api.get("timeout_seconds", 30)
        self.min_interval = float(api.get("min_request_interval", 0.15))
        self.max_retries = int(api.get("max_retries", 5))
        self._local = threading.local()
        self._ua = api.get("user_agent", "polymarket-copybot/1.0")
        self._lock = threading.Lock()
        self._last_request = 0.0
        self.request_count = 0

    # ------------------------------------------------------------------ core
    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": self._ua, "Accept": "application/json"})
            self._local.session = s
        return s

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            self.request_count += 1

    def get(self, url: str, params: Any = None) -> Any:
        """GET with global throttling, retries, exponential backoff and Retry-After support."""
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    retry_after = r.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() \
                        else min(30.0, (2 ** attempt) + random.random())
                    log.warning("HTTP %s on %s - retrying in %.1fs", r.status_code, url, delay)
                    time.sleep(delay)
                    continue
                if r.status_code == 400:
                    raise ValueError(f"400 Bad Request {url}: {r.text[:300]}")
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_err = exc
                delay = min(30.0, (2 ** attempt) + random.random())
                log.warning("Network error on %s (%s) - retrying in %.1fs", url, exc, delay)
                time.sleep(delay)
        raise RuntimeError(f"GET {url} failed after {self.max_retries} retries: {last_err}")

    # ------------------------------------------------------------- data api
    def get_trades_page(self, user: str, limit: int = 1000, cursor: Optional[str] = None,
                        start: Optional[int] = None, end: Optional[int] = None,
                        taker_only: bool = False, side: Optional[str] = None) -> dict:
        params: dict[str, Any] = {"user": user, "taker_only": str(bool(taker_only)).lower()}
        if cursor:
            params["cursor"] = cursor
        else:
            params["limit"] = limit
        if start is not None:
            params["start"] = int(start)
        if end is not None:
            params["end"] = int(end)
        if side:
            params["side"] = side
        return self.get(f"{self.data_api}/trades", params)

    def iter_trades(self, user: str, start: Optional[int] = None, end: Optional[int] = None,
                    taker_only: bool = False, max_rows: Optional[int] = None,
                    page_size: int = 1000) -> Iterator[dict]:
        """Walk the keyset-paginated trade feed (newest first), re-sending the same filters."""
        cursor = None
        n = 0
        while True:
            page = self.get_trades_page(user, page_size, cursor, start, end, taker_only)
            rows = page.get("data") or []
            for row in rows:
                yield row
                n += 1
                if max_rows and n >= max_rows:
                    return
            cursor = (page.get("pagination") or {}).get("next_cursor")
            if not cursor:
                return

    def get_resolutions(self, condition_ids: list[str]) -> list[dict]:
        assert len(condition_ids) <= 20
        res = self.get(f"{self.data_api}/resolutions", {"condition": ",".join(condition_ids)})
        return res.get("data") or []

    def get_tokens(self, condition_ids: Optional[list[str]] = None,
                   token_ids: Optional[list[str]] = None) -> list[dict]:
        params = {}
        if condition_ids:
            params["condition"] = ",".join(condition_ids[:10])
        if token_ids:
            params["token_id"] = ",".join(token_ids[:50])
        res = self.get(f"{self.data_api}/tokens", params)
        return res.get("data") or []

    def iter_positions(self, user: str, status: str = "CLOSED", start: Optional[int] = None,
                       end: Optional[int] = None, page_size: int = 1000) -> Iterator[dict]:
        cursor = None
        while True:
            params: dict[str, Any] = {"user": user, "status": status}
            if start:
                params["start"] = int(start)
            if end:
                params["end"] = int(end)
            if cursor:
                params["cursor"] = cursor
            else:
                params["limit"] = page_size
            page = self.get(f"{self.data_api}/positions", params)
            for row in page.get("data") or []:
                yield row
            cursor = (page.get("pagination") or {}).get("next_cursor")
            if not cursor:
                return

    def get_user_pnl(self, user: str, interval: str = "all", fidelity: str = "1d") -> dict:
        return self.get(f"{self.data_api}/user-pnl",
                        {"user": user, "interval": interval, "fidelity": fidelity}).get("data") or {}

    def get_user_stats(self, user: str) -> dict:
        return self.get(f"{self.data_api}/user-stats", {"user": user}).get("data") or {}

    # ------------------------------------------------------------ gamma api
    def get_gamma_markets(self, condition_ids: list[str], closed: Optional[bool] = None) -> list[dict]:
        params: list[tuple[str, Any]] = [("condition_ids", c) for c in condition_ids]
        params.append(("limit", max(len(condition_ids), 1)))
        if closed is not None:
            params.append(("closed", str(closed).lower()))
        res = self.get(f"{self.gamma_api}/markets", params)
        return res if isinstance(res, list) else []

    # ------------------------------------------------------------- clob api
    def get_midpoint(self, token_id: str) -> Optional[float]:
        try:
            res = self.get(f"{self.clob_api}/midpoint", {"token_id": token_id})
            return float(res["mid"]) if res and res.get("mid") is not None else None
        except (ValueError, RuntimeError, KeyError, TypeError):
            return None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        try:
            res = self.get(f"{self.clob_api}/price", {"token_id": token_id, "side": side})
            return float(res["price"]) if res and res.get("price") is not None else None
        except (ValueError, RuntimeError, KeyError, TypeError):
            return None
