#!/usr/bin/env python3
"""Polymarket copy-trade bot - CLI entry point.

  python main.py collect   [--days 7] [--max-trades N]
  python main.py analyze
  python main.py backtest  [--days 7] [--balance 10000]
  python main.py run --mode paper [--duration SECONDS]
  python main.py run --mode live          (OFF by default - needs live_trading.enabled + API keys)
"""
from __future__ import annotations

import argparse
import sys

from common import load_config


def cmd_collect(cfg: dict, args) -> int:
    from data_collector import DataCollector
    if args.markets_only:
        DataCollector(cfg).refresh_markets()
        return 0
    DataCollector(cfg).run(days=args.days, max_trades=args.max_trades)
    return 0


def cmd_analyze(cfg: dict, args) -> int:
    from strategy_analyzer import StrategyAnalyzer
    StrategyAnalyzer(cfg).run()
    return 0


def cmd_backtest(cfg: dict, args) -> int:
    from run_test import run_backtest
    if args.balance:
        cfg["paper_trading"]["starting_balance"] = float(args.balance)
    if args.days:
        cfg["backtest"]["days"] = float(args.days)
    run_backtest(cfg)
    return 0


def cmd_run(cfg: dict, args) -> int:
    from bot import CopyTradeBot, LiveTradingDisabled
    try:
        bot = CopyTradeBot(cfg, mode=args.mode)
    except LiveTradingDisabled as exc:
        print(f"\n[SAFETY] Live trading refused: {exc}\n")
        return 2
    bot.run(duration=args.duration, max_iterations=args.iterations)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Polymarket copy-trade bot (paper trading by default)")
    p.add_argument("--config", default=None, help="path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="collect the target wallet's trade history")
    c.add_argument("--days", type=float, default=None, help="lookback days (default: config)")
    c.add_argument("--max-trades", type=int, default=None, help="stop after N newest fills")
    c.add_argument("--markets-only", action="store_true", help="only re-resolve market metadata/payouts")

    sub.add_parser("analyze", help="analyse the target's strategy")

    b = sub.add_parser("backtest", help="replay collected history through the paper trader")
    b.add_argument("--days", type=float, default=None)
    b.add_argument("--balance", type=float, default=None)

    r = sub.add_parser("run", help="run the live copy bot")
    r.add_argument("--mode", choices=["paper", "live"], default="paper")
    r.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    r.add_argument("--iterations", type=int, default=None, help="stop after N polling cycles")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    handlers = {"collect": cmd_collect, "analyze": cmd_analyze, "backtest": cmd_backtest, "run": cmd_run}
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
