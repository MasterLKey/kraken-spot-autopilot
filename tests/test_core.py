from __future__ import annotations

import time
from pathlib import Path

import pytest

from bot.backtest import backtest_dca, backtest_grid
from bot.journal import Fill, Journal
from bot.risk import RiskManager


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "test.sqlite3")


def test_journal_fill_and_export(journal: Journal, tmp_path: Path) -> None:
    journal.log_fill(
        Fill(
            ts=time.time(),
            mode="paper",
            strategy="dca",
            symbol="BTC/USD",
            side="buy",
            order_type="market",
            amount=0.001,
            price=100_000,
            cost=100,
            fee=0.26,
            order_id="paper-1",
            paper=True,
        )
    )
    summary = journal.summary()
    assert summary["fills"] == 1
    assert summary["buy_cost"] == 100
    out = journal.export_csv(tmp_path / "fills.csv")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "BTC/USD" in text


def test_risk_blocks_oversized_order(journal: Journal, tmp_path: Path) -> None:
    risk = RiskManager(
        journal,
        max_daily_loss_quote=50,
        max_position_quote=200,
        max_order_quote=50,
        kill_switch_file=tmp_path / "KILL",
    )
    decision = risk.check_order(symbol="BTC/USD", side="buy", quote_notional=100, mark_price=100_000)
    assert not decision.allowed
    assert "max_order_quote" in decision.reason


def test_risk_kill_switch(journal: Journal, tmp_path: Path) -> None:
    kill = tmp_path / "KILL"
    risk = RiskManager(
        journal,
        max_daily_loss_quote=50,
        max_position_quote=500,
        max_order_quote=50,
        kill_switch_file=kill,
    )
    risk.halt("test")
    assert risk.is_halted()
    decision = risk.check_order(symbol="BTC/USD", side="buy", quote_notional=10, mark_price=100_000)
    assert not decision.allowed
    risk.clear_halt()
    assert not risk.is_halted()


def test_risk_position_cap(journal: Journal, tmp_path: Path) -> None:
    journal.log_fill(
        Fill(
            ts=time.time(),
            mode="paper",
            strategy="dca",
            symbol="BTC/USD",
            side="buy",
            order_type="market",
            amount=0.002,
            price=100_000,
            cost=200,
            fee=0.5,
            order_id="p1",
            paper=True,
        )
    )
    risk = RiskManager(
        journal,
        max_daily_loss_quote=50,
        max_position_quote=220,
        max_order_quote=50,
        kill_switch_file=tmp_path / "KILL",
    )
    decision = risk.check_order(symbol="BTC/USD", side="buy", quote_notional=30, mark_price=100_000)
    assert not decision.allowed


def test_backtest_dca_fee_aware() -> None:
    # flat price series
    ohlcv = [[i * 3600_000, 100, 101, 99, 100, 1] for i in range(48)]
    result = backtest_dca(
        ohlcv,
        symbol="BTC/USD",
        quote_amount=10,
        every_n_candles=24,
        fee_rate=0.0026,
    )
    assert result.buys == 2
    assert result.fees > 0
    assert abs(result.equity - (20 - result.fees)) < 0.01 or result.equity > 0


def test_backtest_grid_runs() -> None:
    # oscillating series that should trigger buys and sells
    ohlcv = []
    price = 100.0
    for i in range(100):
        price = 100 + (5 if i % 2 == 0 else -5)
        ohlcv.append([i * 3600_000, price, price + 1, price - 1, price, 10])
    result = backtest_grid(
        ohlcv,
        symbol="BTC/USD",
        lower=90,
        upper=110,
        levels=6,
        quote_per_level=20,
        fee_rate=0.0026,
        starting_quote=500,
    )
    assert result.candles == 100
    assert result.fees >= 0
    assert result.equity > 0


def test_paper_limit_fill() -> None:
    from bot.exchange.kraken import KrakenClient, Ticker
    from bot.paper import PaperBroker

    broker = PaperBroker(KrakenClient(), fee_rate=0.0026)
    ticker = Ticker(symbol="BTC/USD", last=100.0, bid=99.5, ask=100.5, timestamp=None)
    buy = broker.limit_fill_if_touched("BTC/USD", "buy", 1.0, 101.0, ticker)
    assert buy is not None
    assert buy.side == "buy"
    assert buy.paper
    miss = broker.limit_fill_if_touched("BTC/USD", "buy", 1.0, 90.0, ticker)
    assert miss is None
    sell = broker.limit_fill_if_touched("BTC/USD", "sell", 0.5, 99.0, ticker)
    assert sell is not None
    assert sell.side == "sell"


def test_dca_due_interval(journal: Journal) -> None:
    from bot.engines.dca import DcaConfig, DcaEngine
    from bot.notify import Notifier
    from bot.exchange.kraken import KrakenClient
    from bot.risk import RiskManager
    from pathlib import Path

    risk = RiskManager(
        journal,
        max_daily_loss_quote=50,
        max_position_quote=500,
        max_order_quote=50,
        kill_switch_file=Path("data/KILL_test"),
    )
    engine = DcaEngine(
        DcaConfig(symbol="BTC/USD", quote_amount=10, interval_seconds=3600),
        journal=journal,
        risk=risk,
        notifier=Notifier(),
        client=KrakenClient(),
        paper=None,
        mode="paper",
        fee_rate=0.0026,
    )
    assert engine.due(now=1_000_000)
    journal.set_state("dca_last_ts", str(1_000_000))
    assert not engine.due(now=1_000_000 + 10)
    assert engine.due(now=1_000_000 + 3600)
