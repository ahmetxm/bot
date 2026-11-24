"""Copy-trade bot.

CopyEngine   - converts the target's fills into our orders ("canonical position mirroring").
               Shared by the live bot and the backtest so both use identical logic.
CopyTradeBot - polls the Data API every N seconds for new fills of the target wallet and
               mirrors them in paper mode (default) or live mode (OFF by default).

Canonical position mirroring
  The target's net shares per binary market are tracked as (T0, T1). Because one share of each
  outcome is always worth $1 together, (T0, T1) is equivalent to the long-only form
  (T0 + k, T1 + k) with k = -min(T0, T1, 0). Selling an outcome the target never bought (shares
  minted via split) therefore becomes a BUY of the opposite outcome at (1 - price) - the same
  economics, without needing short positions. Increases of the canonical position are copied as
  BUYs scaled by ratio = our_equity / target_capital (fixed per market at first entry);
  decreases are copied as proportional SELLs of whatever we actually hold.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from api_client import PolymarketAPI
from common import classify_market, env_secret, load_json, save_json, setup_logging, utc
from paper_trader import PaperTrader

EPS = 1e-9


class LiveTradingDisabled(RuntimeError):
    pass


@dataclass
class Intent:
    condition_id: str
    outcome_index: int
    side: str           # BUY or SELL
    amount: float       # BUY: our shares ; SELL: fraction of our holding to sell
    ref_price: float    # target's VWAP converted to this outcome


def canonical(t: list[float]) -> tuple[float, float]:
    k = -min(t[0], t[1], 0.0)
    return t[0] + k, t[1] + k


class CopyEngine:
    def __init__(self, target_capital: float, min_order_shares: float = 0.0, min_order_usd: float = 0.0,
                 fixed_ratio: Optional[float] = None):
        self.target_capital = float(target_capital)
        self.min_shares = float(min_order_shares)
        self.min_usd = float(min_order_usd)
        self.fixed_ratio = fixed_ratio
        self.tpos: dict[str, list[float]] = {}
        self.ratio: dict[str, float] = {}
        self.pending_buy: dict[tuple, float] = defaultdict(float)
        self.pending_sell: dict[tuple, float] = defaultdict(float)
        self.stats = defaultdict(int)

    def process(self, cid: str, fills: list[tuple[int, str, float, float]], equity: float) -> list[Intent]:
        """fills: [(outcome_index, side, size, price), ...] of ONE binary market (chronological)."""
        t = self.tpos.setdefault(cid, [0.0, 0.0])
        before = canonical(t)
        num, den = [0.0, 0.0], [0.0, 0.0]
        for idx, side, size, price in fills:
            if idx not in (0, 1):
                self.stats["unsupported_outcome"] += 1
                continue
            t[idx] += size if side == "BUY" else -size
            num[idx] += size * price
            den[idx] += size
            num[1 - idx] += size * (1.0 - price)
            den[1 - idx] += size
        after = canonical(t)
        if cid not in self.ratio:
            self.ratio[cid] = self.fixed_ratio if self.fixed_ratio is not None \
                else max(equity, 0.0) / self.target_capital
        r = self.ratio[cid]
        out = []
        for i in (0, 1):
            d = after[i] - before[i]
            if abs(d) < 1e-9 or den[i] <= 0:
                continue
            vwap = num[i] / den[i]
            if d > 0:
                out.append(Intent(cid, i, "BUY", r * d, vwap))
            else:
                frac = min(1.0, -d / before[i]) if before[i] > 1e-12 else 1.0
                out.append(Intent(cid, i, "SELL", frac, vwap))
        return out

    def execute(self, trader: PaperTrader, it: Intent, ts: float, price: float, meta: dict) -> float:
        """Apply an intent to the trader with minimum-order accumulation. Returns executed shares."""
        key = (it.condition_id, it.outcome_index)
        if it.side == "BUY":
            want = it.amount + self.pending_buy.pop(key, 0.0)
            if want < self.min_shares or want * price < self.min_usd:
                self.pending_buy[key] = want
                self.stats["accumulating_buy"] += 1
                return 0.0
            got = trader.buy(ts, it.condition_id, it.outcome_index, want, price, meta)
            self.stats["buy_executed" if got > 0 else "buy_rejected"] += 1
            return got
        # SELL: shrink pending buys too, then sell the same fraction of what we hold
        if key in self.pending_buy:
            self.pending_buy[key] *= (1.0 - it.amount)
        held = trader.holding(*key)
        qty = held * it.amount + self.pending_sell.pop(key, 0.0)
        if held <= EPS or qty <= EPS:
            return 0.0
        qty = min(qty, held)
        if qty < self.min_shares and qty < held - EPS:
            self.pending_sell[key] = qty
            self.stats["accumulating_sell"] += 1
            return 0.0
        got = trader.sell(ts, it.condition_id, it.outcome_index, qty, price)
        self.stats["sell_executed" if got > 0 else "sell_rejected"] += 1
        return got

    def forget(self, cid: str) -> None:
        self.tpos.pop(cid, None)
        self.ratio.pop(cid, None)
        for i in (0, 1):
            self.pending_buy.pop((cid, i), None)
            self.pending_sell.pop((cid, i), None)

    def to_state(self) -> dict:
        return {"tpos": self.tpos, "ratio": self.ratio, "target_capital": self.target_capital,
                "pending_buy": [[k[0], k[1], v] for k, v in self.pending_buy.items()],
                "pending_sell": [[k[0], k[1], v] for k, v in self.pending_sell.items()]}

    def load_state(self, st: dict) -> None:
        self.tpos = {k: list(v) for k, v in st.get("tpos", {}).items()}
        self.ratio = dict(st.get("ratio", {}))
        self.pending_buy = defaultdict(float, {(a, int(b)): v for a, b, v in st.get("pending_buy", [])})
        self.pending_sell = defaultdict(float, {(a, int(b)): v for a, b, v in st.get("pending_sell", [])})


# ---------------------------------------------------------------------------------------------
class LiveExecutor:
    """Sends real FOK market orders.
    Preferred backend: the official unified SDK `polymarket-client` (pip install polymarket-client, Python >= 3.11),
    which signs CLOB V2 orders. The legacy `py-clob-client` (V1) is only a fallback: since the CLOB V2 migration
    (April 2026) the exchange rejects V1-signed orders ("invalid order version").
    NOT exercised with real orders in this project - it only activates when the user explicitly sets
    live_trading.enabled: true and provides credentials via environment variables."""

    def __init__(self, cfg: dict, log=None):
        lt = cfg["live_trading"]
        ev = lt["env_vars"]
        pk = env_secret(ev["private_key"])
        if not pk:
            raise LiveTradingDisabled(f"missing environment variable {ev['private_key']}")
        self.backend = "polymarket-client"
        try:
            from polymarket import SecureClient
        except ImportError:
            SecureClient = None
        if SecureClient is not None:
            funder = env_secret(ev["funder"])
            self.client = SecureClient.create(private_key=pk, wallet=funder or None)
            return
        self.backend = "py-clob-client"
        if log:
            log.warning("polymarket-client not installed - falling back to legacy py-clob-client, whose V1 orders are "
                        "rejected by the CLOB since the V2 migration. Install: pip install polymarket-client")
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
        except ImportError as exc:
            raise LiveTradingDisabled("no order-signing SDK installed (pip install polymarket-client)") from exc
        self._MarketOrderArgs, self._OrderType, self._BUY, self._SELL = MarketOrderArgs, OrderType, BUY, SELL
        self.client = ClobClient(cfg["api"]["clob_api"], key=pk, chain_id=int(lt.get("chain_id", 137)),
                                 signature_type=int(lt.get("signature_type", 1)),
                                 funder=env_secret(ev["funder"]))
        key, secret, phrase = env_secret(ev["api_key"]), env_secret(ev["api_secret"]), env_secret(ev["api_passphrase"])
        creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=phrase) if key and secret and phrase \
            else self.client.create_or_derive_api_creds()
        self.client.set_api_creds(creds)

    def market_order(self, token_id: str, side: str, amount: float) -> dict:
        """BUY: amount in USDC ; SELL: amount in shares. Fill-or-kill. Returns a dict with a boolean 'success'."""
        if self.backend == "polymarket-client":
            qty = f"{int(amount * 100 + EPS) / 100:.2f}"       # floor to cents/0.01 share: never more than we hold
            try:
                if side == "BUY":
                    signed = self.client.create_market_order(asset_id=token_id, side="BUY", amount=qty,
                                                             order_type="FOK")
                else:
                    signed = self.client.create_market_order(asset_id=token_id, side="SELL", shares=qty,
                                                             order_type="FOK")
                r = self.client.post_order(signed)
            except Exception as exc:  # noqa: BLE001 - e.g. InsufficientLiquidityError, network errors
                return {"success": False, "code": type(exc).__name__, "message": str(exc)}
            if getattr(r, "ok", False):
                return {"success": True, "order_id": r.order_id, "status": r.status,
                        "making_amount": str(r.making_amount), "taking_amount": str(r.taking_amount)}
            return {"success": False, "code": getattr(r, "code", None), "message": getattr(r, "message", str(r))}
        args = self._MarketOrderArgs(token_id=token_id, amount=round(amount, 2),
                                     side=self._BUY if side == "BUY" else self._SELL)
        signed = self.client.create_market_order(args)
        return self.client.post_order(signed, self._OrderType.FOK)


# ---------------------------------------------------------------------------------------------
class CopyTradeBot:
    def __init__(self, cfg: dict, mode: str = "paper", api: Optional[PolymarketAPI] = None):
        self.cfg = cfg
        self.mode = mode
        self.bcfg = cfg["bot"]
        self.api = api or PolymarketAPI(cfg)
        self.log = setup_logging(cfg, f"bot_{mode}")
        self.wallet = cfg["target"]["wallet"].lower()
        self.live: Optional[LiveExecutor] = None
        if mode == "live":
            if not cfg.get("live_trading", {}).get("enabled", False):
                raise LiveTradingDisabled("live_trading.enabled is false in config.yaml (default). "
                                          "Validate the strategy in paper mode first, then enable it manually.")
            self.live = LiveExecutor(cfg, self.log)
            self.log.warning("LIVE TRADING ENABLED - real orders will be sent (backend: %s)", self.live.backend)

        self.trader = PaperTrader(cfg["paper_trading"]["starting_balance"], cfg["risk"], cfg["fees"],
                                  name=mode, enforce_limits=True, apply_fees=True, logger=self.log,
                                  log_each_trade=True)
        self.engine = CopyEngine(self._target_capital(), cfg["risk"].get("min_order_shares", 0),
                                 cfg["risk"].get("min_order_usd", 0))
        self.state_path = Path(cfg["paths"]["data_dir"]).parent / self.bcfg.get("state_file", "data/bot_state.json")
        if mode == "live":
            self.state_path = self.state_path.with_name("bot_state_live.json")
        self.seen: deque = deque(maxlen=20000)
        self.seen_set: set = set()
        self.last_ts: Optional[int] = None
        self.tokens: dict[str, list[Optional[str]]] = {}
        self.market_info: dict[str, dict] = {}
        self.closed: set = set()
        self.slippage = cfg["backtest"].get("slippage_bps", 30) / 1e4
        self._load_state()

    # ------------------------------------------------------------- setup
    def _target_capital(self) -> float:
        rep = load_json(Path(self.cfg["paths"]["reports_dir"]) / "performance_report.json", {})
        cap = (rep.get("assumptions") or {}).get("target_capital_usd")
        manual = self.cfg["sizing"].get("target_capital_usd")
        if isinstance(manual, (int, float)):
            cap = float(manual)
        cap = float(cap or self.cfg["sizing"].get("fallback_target_capital_usd", 50000))
        self.log.info("Sizing: our_shares = target_shares x equity / %.0f (target capital estimate)", cap)
        return cap

    def _load_state(self) -> None:
        st = load_json(self.state_path)
        if not st:
            return
        self.trader.load_state(st["trader"])
        self.engine.load_state(st.get("engine", {}))
        self.last_ts = st.get("last_ts")
        for k in st.get("seen", []):
            self._mark_seen(tuple(k))
        self.tokens = st.get("tokens", {})
        self.market_info = st.get("market_info", {})
        self.closed = set(st.get("closed", []))
        self.log.info("Resumed state: equity %.2f, %d open positions", self.trader.equity(), len(self.trader.positions))

    def _save_state(self) -> None:
        save_json({"trader": self.trader.to_state(), "engine": self.engine.to_state(), "last_ts": self.last_ts,
                   "seen": [list(k) for k in self.seen], "tokens": self.tokens, "market_info": self.market_info,
                   "closed": sorted(self.closed)[-5000:], "saved_at": utc(time.time())}, self.state_path)

    def _mark_seen(self, key: tuple) -> None:
        if len(self.seen) == self.seen.maxlen:
            self.seen_set.discard(self.seen[0])
        self.seen.append(key)
        self.seen_set.add(key)

    @staticmethod
    def _key(t: dict) -> tuple:
        return (t.get("transaction_hash"), t.get("token_id"), t.get("side"), t.get("size"), t.get("price"),
                t.get("timestamp"))

    # ----------------------------------------------------------- polling
    def fetch_new_fills(self) -> list[dict]:
        taker_only = not self.bcfg.get("copy_maker_fills", True)
        new, cursor = [], None
        for _ in range(5):  # at most 5 pages per poll
            page = self.api.get_trades_page(self.wallet, limit=200, cursor=cursor, taker_only=taker_only)
            rows = page.get("data") or []
            fresh = [r for r in rows if self._key(r) not in self.seen_set
                     and (self.last_ts is None or int(r["timestamp"]) >= self.last_ts - 5)]
            new.extend(fresh)
            cursor = (page.get("pagination") or {}).get("next_cursor")
            if len(fresh) < len(rows) or not cursor or self.last_ts is None:
                break
        if self.last_ts is None:
            # first poll: remember existing history, copy only what happens from now on
            for r in new:
                self._mark_seen(self._key(r))
            self.last_ts = max((int(r["timestamp"]) for r in new), default=int(time.time()))
            self.log.info("Initialised at %s - %d historical fills marked as seen (not copied)",
                          utc(self.last_ts), len(new))
            return []
        for r in new:
            self._mark_seen(self._key(r))
        if new:
            self.last_ts = max(self.last_ts, max(int(r["timestamp"]) for r in new))
        return sorted(new, key=lambda r: int(r["timestamp"]))

    def _token_ids(self, cid: str, fill: dict) -> list[Optional[str]]:
        toks = self.tokens.get(cid)
        if toks is None or None in toks:
            toks = toks or [None, None]
            try:
                for t in self.api.get_tokens(condition_ids=[cid]):
                    if t.get("outcome_index") in (0, 1):
                        toks[int(t["outcome_index"])] = str(t["token_id"])
            except (RuntimeError, ValueError) as exc:
                self.log.warning("token lookup failed for %s: %s", cid[:10], exc)
            idx = int(fill.get("outcome_index", 999))
            if idx in (0, 1) and not toks[idx]:
                toks[idx] = str(fill.get("token_id"))
            self.tokens[cid] = toks
        return toks

    def _exec_price(self, token_id: Optional[str], side: str, ref: float) -> Optional[float]:
        """Current executable price from the CLOB (midpoint + slippage); falls back to target VWAP."""
        mid = self.api.get_midpoint(token_id) if token_id else None
        px = mid if mid is not None and 0 < mid < 1 else ref
        px = px * (1 + self.slippage) if side == "BUY" else px * (1 - self.slippage)
        return min(max(px, 0.001), 0.999)

    def handle_fills(self, fills: list[dict]) -> None:
        now = time.time()
        max_age = float(self.bcfg.get("max_trade_age_seconds", 60))
        by_market: dict[str, list[dict]] = defaultdict(list)
        for f in fills:
            if now - int(f["timestamp"]) > max_age:
                self.engine.stats["stale_fill_skipped"] += 1
                continue
            by_market[f["condition_id"]].append(f)
        for cid, group in by_market.items():
            f0 = group[0]
            info = self.market_info.get(cid) or {"title": f0.get("title", ""), "slug": f0.get("slug", ""),
                                                 **classify_market(f0.get("slug", ""), f0.get("title", ""))}
            self.market_info[cid] = info
            meta = {"title": info["title"], "category": info["category"], "slug": info["slug"]}
            if info.get("window_end") and now >= info["window_end"]:
                self.engine.stats["market_closed"] += 1
                continue
            intents = self.engine.process(cid, [(int(f["outcome_index"]), f["side"], float(f["size"]),
                                                 float(f["price"])) for f in group], self.trader.equity())
            toks = self._token_ids(cid, f0)
            for it in intents:
                tok = toks[it.outcome_index]
                px = self._exec_price(tok, it.side, it.ref_price)
                self.log.info("Target %s -> intent %s outcome %d %.4f @ ref %.4f / exec %.4f | %s",
                              f0.get("side"), it.side, it.outcome_index, it.amount, it.ref_price, px, info["title"])
                if self.live is not None:
                    self._execute_live(it, tok, px, meta, now)
                else:
                    self.engine.execute(self.trader, it, now, px, meta)

    def _execute_live(self, it: Intent, token_id: Optional[str], px: float, meta: dict, now: float) -> None:
        if not token_id:
            self.log.error("No token id for %s - order skipped", it.condition_id[:10])
            return
        self.trader.market_meta.setdefault(it.condition_id, meta)
        if it.side == "BUY":
            shares = self.trader.size_buy(now, it.condition_id, it.amount, px)
            if shares <= 0:
                return
            resp = self.live.market_order(token_id, "BUY", shares * px)
        else:
            shares = self.trader.holding(it.condition_id, it.outcome_index) * it.amount
            if shares < self.cfg["risk"].get("min_order_shares", 0):
                return
            resp = self.live.market_order(token_id, "SELL", shares)
        self.log.warning("LIVE order %s %s %.2f sh -> %s", it.side, token_id[:12], shares, resp)
        if isinstance(resp, dict) and resp.get("success"):
            if it.side == "BUY":
                self.trader.buy(now, it.condition_id, it.outcome_index, shares, px, meta, reason="live")
            else:
                self.trader.sell(now, it.condition_id, it.outcome_index, shares, px, reason="live")

    # ---------------------------------------------------- resolution / MTM
    def check_resolutions(self) -> None:
        pending = [c for c in self.trader.market_deployed if c not in self.closed]
        for i in range(0, len(pending), 20):
            batch = pending[i:i + 20]
            try:
                res = self.api.get_resolutions(batch)
            except (RuntimeError, ValueError) as exc:
                self.log.warning("resolution check failed: %s", exc)
                continue
            for r in res:
                cid = r.get("condition_id")
                if r.get("status") == "resolved" and r.get("payouts"):
                    pnl = self.trader.resolve(time.time(), cid, r["payouts"])
                    self.closed.add(cid)
                    self.engine.forget(cid)
                    if pnl is not None:
                        self.log.info("RESOLVED %s payouts=%s -> market PnL %.2f",
                                      self.market_info.get(cid, {}).get("title", cid[:10]), r["payouts"], pnl)

    def mark_to_market(self) -> None:
        now = time.time()
        for (cid, idx), pos in list(self.trader.positions.items()):
            tok = (self.tokens.get(cid) or [None, None])[idx]
            mid = self.api.get_midpoint(tok) if tok else None
            if mid is not None and 0 < mid < 1:
                self.trader.mark(now, cid, idx, mid)
        self.trader.snapshot(now)

    # --------------------------------------------------------------- loop
    def run(self, duration: Optional[float] = None, max_iterations: Optional[int] = None,
            sleep_fn: Callable[[float], None] = time.sleep) -> dict:
        poll = float(self.bcfg.get("poll_interval_seconds", 10))
        res_every = float(self.bcfg.get("resolution_check_seconds", 30))
        mtm_every = float(self.bcfg.get("mark_to_market_seconds", 30))
        t_start = time.time()
        last_res = last_mtm = 0.0
        it = 0
        self.log.info("Copy bot started | mode=%s | target=%s | poll=%ss | equity=%.2f",
                      self.mode, self.wallet, poll, self.trader.equity())
        try:
            while True:
                t0 = time.time()
                try:
                    fills = self.fetch_new_fills()
                    if fills:
                        self.log.info("Detected %d new target fills", len(fills))
                        self.handle_fills(fills)
                    if t0 - last_res >= res_every:
                        self.check_resolutions()
                        last_res = t0
                    if t0 - last_mtm >= mtm_every:
                        self.mark_to_market()
                        last_mtm = t0
                except (RuntimeError, ValueError) as exc:
                    self.log.error("cycle error: %s", exc)
                it += 1
                self._save_state()
                if it % 6 == 0 or it == 1:
                    m = self.trader
                    self.log.info("Status | equity %.2f | cash %.2f | open %d | orders %d | last target fill %s",
                                  m.equity(), m.cash, len(m.positions), len(m.trade_log),
                                  utc(self.last_ts) if self.last_ts else "-")
                if (max_iterations and it >= max_iterations) or (duration and time.time() - t_start >= duration):
                    break
                sleep_fn(max(0.0, poll - (time.time() - t0)))
        except KeyboardInterrupt:
            self.log.info("Interrupted by user")
        finally:
            self._save_state()
        summary = self.trader.metrics()
        summary["engine_stats"] = dict(self.engine.stats)
        save_json(summary, Path(self.cfg["paths"]["reports_dir"]) / f"bot_{self.mode}_session.json")
        self.log.info("Session finished | equity %.2f | PnL %.2f | orders %d", summary["final_equity"],
                      summary["total_pnl"], summary["n_orders"])
        return summary
