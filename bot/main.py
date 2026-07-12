from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bot.backtest import backtest_dca, backtest_grid
from bot.config import Settings, get_settings
from bot.engines.dca import DcaConfig, DcaEngine
from bot.engines.grid import GridConfig, GridEngine
from bot.exchange.kraken import KrakenClient
from bot.journal import Journal
from bot.logging_setup import setup_logging
from bot.notify import Notifier
from bot.paper import PaperBroker
from bot.risk import RiskManager

log = setup_logging()


class BotApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.journal = Journal(settings.db_path())
        self.notifier = Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
        self.risk = RiskManager(
            self.journal,
            max_daily_loss_quote=settings.max_daily_loss_quote,
            max_position_quote=settings.max_position_quote,
            max_order_quote=settings.max_order_quote,
            kill_switch_file=settings.kill_switch_file,
        )
        self.client = KrakenClient(
            api_key=settings.kraken_api_key,
            api_secret=settings.kraken_api_secret,
            fee_rate=settings.fee_rate,
        )
        self.paper = PaperBroker(self.client, settings.fee_rate) if settings.is_paper else None
        self.dca: DcaEngine | None = None
        self.grid: GridEngine | None = None
        self._running = True

        if settings.strategy in ("dca", "both") and settings.dca_enabled:
            self.dca = DcaEngine(
                DcaConfig(
                    symbol=settings.symbol,
                    quote_amount=settings.dca_quote_amount,
                    interval_seconds=settings.dca_interval_seconds,
                    dip_pct=settings.dca_dip_pct,
                ),
                journal=self.journal,
                risk=self.risk,
                notifier=self.notifier,
                client=self.client,
                paper=self.paper,
                mode=settings.bot_mode,
                fee_rate=settings.fee_rate,
            )

        if settings.strategy in ("grid", "both") and settings.grid_enabled:
            self.grid = GridEngine(
                GridConfig(
                    symbol=settings.symbol,
                    lower=settings.grid_lower_price,
                    upper=settings.grid_upper_price,
                    levels=settings.grid_levels,
                    quote_per_level=settings.grid_quote_per_level,
                    base_reserve=settings.grid_base_reserve,
                ),
                journal=self.journal,
                risk=self.risk,
                notifier=self.notifier,
                client=self.client,
                paper=self.paper,
                mode=settings.bot_mode,
                fee_rate=settings.fee_rate,
            )

    def validate(self) -> None:
        if self.settings.is_live:
            if not self.settings.kraken_api_key or not self.settings.kraken_api_secret:
                raise SystemExit("Live mode requires KRAKEN_API_KEY and KRAKEN_API_SECRET")
        if self.grid is None and self.dca is None:
            raise SystemExit("No strategy enabled — set STRATEGY and enable DCA/GRID")

    def run_forever(self) -> None:
        self.validate()
        mode = self.settings.bot_mode.upper()
        log.info(
            "Starting Kraken Spot Autopilot mode=%s strategy=%s symbol=%s",
            mode,
            self.settings.strategy,
            self.settings.symbol,
        )
        self.notifier.send(f"Bot started ({mode}) {self.settings.symbol} strategy={self.settings.strategy}")
        self.journal.log_event("start", f"mode={mode} strategy={self.settings.strategy}")

        def _stop(signum, _frame):
            log.info("Signal %s received — shutting down", signum)
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        consecutive_errors = 0
        ticks = 0
        while self._running:
            try:
                if self.risk.is_halted():
                    log.warning("Kill switch active — idling (clear via: python -m bot halt --clear)")
                    time.sleep(self.settings.poll_interval_seconds)
                    continue

                # Refresh markets periodically to survive pair/filter changes
                ticks += 1
                if ticks == 1 or ticks % 120 == 0:
                    self.client.load_markets(reload=ticks > 1)

                if self.dca:
                    self.dca.tick()
                if self.grid:
                    self.grid.tick()

                consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001 — keep loop alive
                consecutive_errors += 1
                log.exception("Tick failed (%s): %s", consecutive_errors, exc)
                self.journal.log_event("error", str(exc), level="ERROR")
                try:
                    self.client.load_markets(reload=True)
                except Exception:  # noqa: BLE001
                    pass
                if consecutive_errors >= 10:
                    self.risk.halt(f"too many errors: {exc}")
                    self.notifier.send(f"Bot halted after repeated errors: {exc}")
                time.sleep(min(2 ** consecutive_errors, 60))
                continue

            time.sleep(self.settings.poll_interval_seconds)

        self.notifier.send("Bot stopped")
        self.journal.log_event("stop", "clean shutdown")
        self.journal.close()
        log.info("Stopped")


def cmd_run(_args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    BotApp(settings).run_forever()


def cmd_status(_args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    journal = Journal(settings.db_path())
    summary = journal.summary()
    halted = settings.kill_switch_file.exists()
    print(f"mode={settings.bot_mode} symbol={settings.symbol} strategy={settings.strategy}")
    print(f"kill_switch={'ON' if halted else 'off'}")
    print(f"fills={summary['fills']} buy_cost={summary['buy_cost']:.2f} sell_proceeds={summary['sell_proceeds']:.2f} fees={summary['fees']:.4f}")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"daily_pnl_quote={journal.get_daily_pnl(day):.4f}")
    base, quote = journal.position_cost_basis(settings.symbol)
    print(f"position_base={base:.8f} position_quote_spent={quote:.2f}")
    journal.close()


def cmd_export(args: argparse.Namespace) -> None:
    settings = get_settings()
    journal = Journal(settings.db_path())
    out = Path(args.output) if args.output else settings.data_dir / "exports" / "fills.csv"
    path = journal.export_csv(out)
    print(f"Exported fills to {path}")
    journal.close()


def cmd_halt(args: argparse.Namespace) -> None:
    settings = get_settings()
    journal = Journal(settings.db_path())
    risk = RiskManager(
        journal,
        max_daily_loss_quote=settings.max_daily_loss_quote,
        max_position_quote=settings.max_position_quote,
        max_order_quote=settings.max_order_quote,
        kill_switch_file=settings.kill_switch_file,
    )
    if args.clear:
        risk.clear_halt()
        print("Kill switch cleared")
    else:
        risk.halt(args.reason or "cli halt")
        print("Kill switch engaged")
    journal.close()


def cmd_ticker(_args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    client = KrakenClient(fee_rate=settings.fee_rate)
    ticker = client.fetch_ticker(settings.symbol)
    print(f"{ticker.symbol} last={ticker.last} bid={ticker.bid} ask={ticker.ask}")


def cmd_health(_args: argparse.Namespace) -> None:
    """Connectivity + config sanity check (does not place orders)."""
    settings = get_settings()
    setup_logging(settings.log_level)
    client = KrakenClient(
        api_key=settings.kraken_api_key,
        api_secret=settings.kraken_api_secret,
        fee_rate=settings.fee_rate,
    )
    client.load_markets()
    ticker = client.fetch_ticker(settings.symbol)
    print(f"ok markets loaded symbol={settings.symbol} last={ticker.last}")
    print(f"mode={settings.bot_mode} strategy={settings.strategy}")
    if settings.is_live:
        bal = client.fetch_balance()
        free = bal.get("free") or {}
        quote = settings.symbol.split("/")[-1]
        print(f"live balance free {quote}={free.get(quote, 'n/a')}")
    else:
        print("paper mode - skipping private balance")
    kill = "ON" if settings.kill_switch_file.exists() else "off"
    print(f"kill_switch={kill}")


def cmd_backtest(args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    client = KrakenClient(fee_rate=settings.fee_rate)
    ohlcv = client.fetch_ohlcv(settings.symbol, timeframe=args.timeframe, limit=args.limit)
    if args.strategy == "dca":
        result = backtest_dca(
            ohlcv,
            symbol=settings.symbol,
            quote_amount=settings.dca_quote_amount,
            every_n_candles=args.every,
            fee_rate=settings.fee_rate,
        )
    else:
        lower = settings.grid_lower_price or args.lower
        upper = settings.grid_upper_price or args.upper
        if lower <= 0 or upper <= 0:
            # Auto band around last close ± pct
            last = float(ohlcv[-1][4])
            band = args.band_pct / 100.0
            lower = last * (1.0 - band)
            upper = last * (1.0 + band)
        result = backtest_grid(
            ohlcv,
            symbol=settings.symbol,
            lower=lower,
            upper=upper,
            levels=settings.grid_levels,
            quote_per_level=settings.grid_quote_per_level,
            fee_rate=settings.fee_rate,
            starting_quote=args.capital,
        )
    print(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot", description="Kraken Spot Autopilot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the trading loop")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Show journal / risk status")
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="Export fills to CSV")
    p_export.add_argument("-o", "--output", help="Output CSV path")
    p_export.set_defaults(func=cmd_export)

    p_halt = sub.add_parser("halt", help="Engage or clear kill switch")
    p_halt.add_argument("--clear", action="store_true", help="Clear kill switch")
    p_halt.add_argument("--reason", default="cli halt")
    p_halt.set_defaults(func=cmd_halt)

    p_ticker = sub.add_parser("ticker", help="Fetch live ticker (public)")
    p_ticker.set_defaults(func=cmd_ticker)

    p_health = sub.add_parser("health", help="Connectivity and config sanity check")
    p_health.set_defaults(func=cmd_health)

    p_bt = sub.add_parser("backtest", help="Fee-aware DCA/grid backtest on Kraken OHLCV")
    p_bt.add_argument("--strategy", choices=["dca", "grid"], default="grid")
    p_bt.add_argument("--timeframe", default="1h")
    p_bt.add_argument("--limit", type=int, default=500)
    p_bt.add_argument("--every", type=int, default=24, help="DCA every N candles")
    p_bt.add_argument("--capital", type=float, default=1000.0)
    p_bt.add_argument("--lower", type=float, default=0.0)
    p_bt.add_argument("--upper", type=float, default=0.0)
    p_bt.add_argument("--band-pct", type=float, default=10.0, help="Auto grid band %% around last close")
    p_bt.set_defaults(func=cmd_backtest)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
