from __future__ import annotations

import time
import uuid
from typing import Optional

from bot.exchange.kraken import KrakenClient, OrderResult, Ticker
from bot.logging_setup import get_logger

log = get_logger("bot.paper")


class PaperBroker:
    """Simulates fills against live ticker prices; never hits private endpoints."""

    def __init__(self, client: KrakenClient, fee_rate: float) -> None:
        self.client = client
        self.fee_rate = fee_rate
        self.base_balance = 0.0
        self.quote_balance = 10_000.0  # virtual quote for paper sims

    def fetch_ticker(self, symbol: str) -> Ticker:
        return self.client.fetch_ticker(symbol)

    def market_buy_quote(self, symbol: str, quote_amount: float) -> OrderResult:
        ticker = self.fetch_ticker(symbol)
        price = ticker.ask if ticker.ask > 0 else ticker.last
        if price <= 0:
            raise ValueError(f"Bad paper price for {symbol}")
        fee = quote_amount * self.fee_rate
        spend = quote_amount - fee
        amount = spend / price
        self.quote_balance -= quote_amount
        self.base_balance += amount
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        log.info("PAPER market buy %s amount=%.8f @ %.2f cost=%.2f fee=%.4f", symbol, amount, price, quote_amount, fee)
        return OrderResult(
            id=order_id,
            symbol=symbol,
            side="buy",
            type="market",
            amount=amount,
            price=price,
            cost=quote_amount,
            status="closed",
            raw={"fee": fee, "paper": True},
            paper=True,
        )

    def limit_fill_if_touched(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        ticker: Optional[Ticker] = None,
    ) -> Optional[OrderResult]:
        ticker = ticker or self.fetch_ticker(symbol)
        touched = False
        if side == "buy" and ticker.ask <= price:
            touched = True
            fill_price = min(price, ticker.ask)
        elif side == "sell" and ticker.bid >= price:
            touched = True
            fill_price = max(price, ticker.bid)
        else:
            return None

        if not touched:
            return None

        cost = amount * fill_price
        fee = cost * self.fee_rate
        if side == "buy":
            self.quote_balance -= cost + fee
            self.base_balance += amount
        else:
            self.base_balance -= amount
            self.quote_balance += cost - fee

        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        log.info(
            "PAPER limit %s %s amount=%.8f @ %.2f fee=%.4f",
            side,
            symbol,
            amount,
            fill_price,
            fee,
        )
        return OrderResult(
            id=order_id,
            symbol=symbol,
            side=side,
            type="limit",
            amount=amount,
            price=fill_price,
            cost=cost,
            status="closed",
            raw={"fee": fee, "paper": True, "ts": time.time()},
            paper=True,
        )
