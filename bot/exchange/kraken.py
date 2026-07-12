from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import ccxt

from bot.logging_setup import get_logger

log = get_logger("bot.exchange")


@dataclass
class Ticker:
    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: Optional[int]


@dataclass
class OrderResult:
    id: str
    symbol: str
    side: str
    type: str
    amount: float
    price: Optional[float]
    cost: Optional[float]
    status: str
    raw: dict[str, Any]
    paper: bool = False


class KrakenClient:
    """Thin ccxt wrapper with retry/backoff for Kraken spot."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        fee_rate: float = 0.0026,
        max_retries: int = 5,
    ) -> None:
        self.fee_rate = fee_rate
        self.max_retries = max_retries
        opts: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if api_key and api_secret:
            opts["apiKey"] = api_key
            opts["secret"] = api_secret
        self.exchange = ccxt.kraken(opts)
        self._markets_loaded = False

    def load_markets(self, reload: bool = False) -> None:
        if self._markets_loaded and not reload:
            return
        self._with_retry(lambda: self.exchange.load_markets(reload))
        self._markets_loaded = True

    def _with_retry(self, fn, *, what: str = "request"):
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()
            except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as exc:
                last_err = exc
                log.warning("%s failed (%s/%s): %s — retry in %.1fs", what, attempt, self.max_retries, exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
            except ccxt.DDoSProtection as exc:
                last_err = exc
                log.warning("Rate limited on %s — sleeping %.1fs", what, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        assert last_err is not None
        raise last_err

    def fetch_ticker(self, symbol: str) -> Ticker:
        self.load_markets()
        raw = self._with_retry(lambda: self.exchange.fetch_ticker(symbol), what=f"ticker {symbol}")
        last = float(raw.get("last") or raw.get("close") or 0)
        bid = float(raw.get("bid") or last)
        ask = float(raw.get("ask") or last)
        return Ticker(symbol=symbol, last=last, bid=bid, ask=ask, timestamp=raw.get("timestamp"))

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 500) -> list[list]:
        self.load_markets()
        return self._with_retry(
            lambda: self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit),
            what=f"ohlcv {symbol}",
        )

    def fetch_balance(self) -> dict[str, Any]:
        return self._with_retry(lambda: self.exchange.fetch_balance(), what="balance")

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        self.load_markets()
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        self.load_markets()
        return float(self.exchange.price_to_precision(symbol, price))

    def create_market_buy_quote(self, symbol: str, quote_amount: float) -> OrderResult:
        """Market buy spending approximately `quote_amount` of quote currency."""
        self.load_markets()
        ticker = self.fetch_ticker(symbol)
        if ticker.ask <= 0:
            raise ValueError(f"Invalid ask for {symbol}")
        amount = self.amount_to_precision(symbol, quote_amount / ticker.ask)

        def _place():
            # Kraken via ccxt: market buy with cost when supported
            try:
                return self.exchange.create_order(
                    symbol,
                    "market",
                    "buy",
                    amount,
                    None,
                    {"cost": quote_amount},
                )
            except ccxt.InvalidOrder:
                return self.exchange.create_order(symbol, "market", "buy", amount)

        raw = self._with_retry(_place, what=f"market buy {symbol}")
        return self._to_order(raw, paper=False)

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> OrderResult:
        self.load_markets()
        amount = self.amount_to_precision(symbol, amount)
        price = self.price_to_precision(symbol, price)

        raw = self._with_retry(
            lambda: self.exchange.create_order(symbol, "limit", side, amount, price),
            what=f"limit {side} {symbol}",
        )
        return self._to_order(raw, paper=False)

    def cancel_order(self, order_id: str, symbol: str) -> None:
        self._with_retry(lambda: self.exchange.cancel_order(order_id, symbol), what="cancel")

    def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        return self._with_retry(lambda: self.exchange.fetch_open_orders(symbol), what="open orders")

    @staticmethod
    def _to_order(raw: dict[str, Any], *, paper: bool) -> OrderResult:
        return OrderResult(
            id=str(raw.get("id") or raw.get("clientOrderId") or "unknown"),
            symbol=str(raw.get("symbol") or ""),
            side=str(raw.get("side") or ""),
            type=str(raw.get("type") or ""),
            amount=float(raw.get("amount") or 0),
            price=(float(raw["price"]) if raw.get("price") is not None else None),
            cost=(float(raw["cost"]) if raw.get("cost") is not None else None),
            status=str(raw.get("status") or "unknown"),
            raw=raw,
            paper=paper,
        )
