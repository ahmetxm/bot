#!/usr/bin/env python3
"""Polymarket bot - CLI entry point.

Strategy replica (recommended - imitates the target's market-making logic, does not copy its trades):
  python main.py fetch-tapes        [--days 4]       download resolved markets, trade tapes, Binance spot
  python main.py latency-probe      [--seconds 240]  measure how late Data API trade timestamps are
  python main.py strategy-backtest  [--days N] [--no-grid]   calibrate on train, test out-of-sample
  python main.py paper-live         [--minutes 60] [--tag NAME] [--set key=value]   live PAPER trading

Copy-trading (first attempt, kept for reference):
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


PASSTHROUGH = {   # command -> (module, help); remaining arguments are handed to module.main()
    "fetch-tapes": ("market_data", "download resolved markets + trade tapes + spot history"),
    "latency-probe": ("latency_probe", "measure Data API timestamp delay vs the CLOB websocket"),
    "strategy-backtest": ("strategy_backtest", "calibrate + backtest the strategy replica"),
    "paper-live": ("live_paper", "live PAPER trading of the strategy replica (no real orders)"),
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH:
        import importlib
        importlib.import_module(PASSTHROUGH[argv[0]][0]).main(argv[1:])
        return 0
    p = argparse.ArgumentParser(description="Polymarket bot (paper trading by default)")
    p.add_argument("--config", default=None, help="path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)
    for name, (_, hlp) in PASSTHROUGH.items():
        sub.add_parser(name, help=hlp + " (see: python main.py %s --help)" % name)

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
