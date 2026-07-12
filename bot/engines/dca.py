from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from bot.exchange.kraken import KrakenClient, OrderResult
from bot.journal import Fill, Journal
from bot.logging_setup import get_logger
from bot.notify import Notifier
from bot.paper import PaperBroker
from bot.risk import RiskManager

log = get_logger("bot.dca")


class ExecutionBackend(Protocol):
    def market_buy_quote(self, symbol: str, quote_amount: float) -> OrderResult: ...


@dataclass
class DcaConfig:
    symbol: str
    quote_amount: float
    interval_seconds: int
    dip_pct: float = 0.0


class DcaEngine:
    def __init__(
        self,
        cfg: DcaConfig,
        *,
        journal: Journal,
        risk: RiskManager,
        notifier: Notifier,
        client: KrakenClient,
        paper: Optional[PaperBroker],
        mode: str,
        fee_rate: float,
    ) -> None:
        self.cfg = cfg
        self.journal = journal
        self.risk = risk
        self.notifier = notifier
        self.client = client
        self.paper = paper
        self.mode = mode
        self.fee_rate = fee_rate
        self._ref_price: Optional[float] = None

    def _backend_buy(self, quote_amount: float) -> OrderResult:
        if self.mode == "paper":
            assert self.paper is not None
            return self.paper.market_buy_quote(self.cfg.symbol, quote_amount)
        return self.client.create_market_buy_quote(self.cfg.symbol, quote_amount)

    def due(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        last = self.journal.get_state("dca_last_ts")
        if last is None:
            return True
        return (now - float(last)) >= self.cfg.interval_seconds

    def _dip_ok(self, last_price: float) -> bool:
        if self.cfg.dip_pct <= 0:
            return True
        if self._ref_price is None:
            stored = self.journal.get_state("dca_ref_price")
            self._ref_price = float(stored) if stored else last_price
            self.journal.set_state("dca_ref_price", str(self._ref_price))
        threshold = self._ref_price * (1.0 - self.cfg.dip_pct / 100.0)
        if last_price <= threshold:
            return True
        log.info(
            "DCA waiting for dip: last=%.2f threshold=%.2f (ref=%.2f - %.2f%%)",
            last_price,
            threshold,
            self._ref_price,
            self.cfg.dip_pct,
        )
        return False

    def tick(self) -> Optional[OrderResult]:
        if not self.due():
            return None

        ticker = self.client.fetch_ticker(self.cfg.symbol)
        if not self._dip_ok(ticker.last):
            return None

        decision = self.risk.check_order(
            symbol=self.cfg.symbol,
            side="buy",
            quote_notional=self.cfg.quote_amount,
            mark_price=ticker.last,
        )
        if not decision.allowed:
            log.warning("DCA blocked by risk: %s", decision.reason)
            self.journal.log_event("dca_blocked", decision.reason, level="WARNING")
            return None

        order = self._backend_buy(self.cfg.quote_amount)
        price = float(order.price or ticker.ask or ticker.last)
        cost = float(order.cost or self.cfg.quote_amount)
        fee = float(order.raw.get("fee") or cost * self.fee_rate)
        fill = Fill(
            ts=time.time(),
            mode=self.mode,
            strategy="dca",
            symbol=self.cfg.symbol,
            side="buy",
            order_type=order.type,
            amount=order.amount,
            price=price,
            cost=cost,
            fee=fee,
            order_id=order.id,
            paper=order.paper,
            note="scheduled DCA",
        )
        self.journal.log_fill(fill)
        self.journal.set_state("dca_last_ts", str(time.time()))
        self._ref_price = price
        self.journal.set_state("dca_ref_price", str(price))

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Buys themselves aren't realized loss; fees count as drag
        self.journal.add_daily_pnl(day, -fee)

        msg = (
            f"DCA {self.mode.upper()} buy {self.cfg.symbol}\n"
            f"amount={order.amount:.8f} price={price:.2f} cost={cost:.2f} fee={fee:.4f}"
        )
        log.info(msg.replace("\n", " | "))
        self.notifier.send(msg)
        return order
