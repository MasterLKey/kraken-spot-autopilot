from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from bot.logging_setup import get_logger

log = get_logger("bot.backtest")


@dataclass
class BacktestResult:
    symbol: str
    candles: int
    buys: int
    sells: int
    quote_spent: float
    quote_received: float
    fees: float
    final_base: float
    final_quote: float
    end_price: float
    equity: float
    return_pct: float


def backtest_grid(
    ohlcv: Iterable[list],
    *,
    symbol: str,
    lower: float,
    upper: float,
    levels: int,
    quote_per_level: float,
    fee_rate: float,
    starting_quote: float,
) -> BacktestResult:
    """Fee-aware geometric spot grid replay on OHLCV closes.

    ohlcv rows: [ts, open, high, low, close, volume]
    """
    candles = list(ohlcv)
    if not candles:
        raise ValueError("No OHLCV data")
    if lower <= 0 or upper <= lower or levels < 2:
        raise ValueError("Invalid grid bounds")

    step = (upper - lower) / (levels - 1)
    mid = (lower + upper) / 2.0
    prices = [lower + step * i for i in range(levels)]
    grid = []
    for price in prices:
        if abs(price - mid) < step * 0.25:
            continue
        side = "buy" if price < mid else "sell"
        grid.append({"price": price, "side": side})

    quote = starting_quote
    base = 0.0
    buys = sells = 0
    quote_spent = quote_received = fees = 0.0
    end_price = float(candles[-1][4])

    for row in candles:
        high = float(row[2])
        low = float(row[3])
        end_price = float(row[4])

        for level in grid:
            price = level["price"]
            side = level["side"]
            amount = quote_per_level / price
            cost = amount * price
            fee = cost * fee_rate

            if side == "buy" and low <= price:
                if quote < cost + fee:
                    continue
                quote -= cost + fee
                base += amount
                quote_spent += cost
                fees += fee
                buys += 1
                level["side"] = "sell"
                level["price"] = min(upper, max(mid, price * 1.002))
            elif side == "sell" and high >= price and base >= amount:
                quote += cost - fee
                base -= amount
                quote_received += cost
                fees += fee
                sells += 1
                level["side"] = "buy"
                level["price"] = max(lower, min(mid, price * 0.998))

    equity = quote + base * end_price
    return_pct = ((equity / starting_quote) - 1.0) * 100.0 if starting_quote else 0.0
    result = BacktestResult(
        symbol=symbol,
        candles=len(candles),
        buys=buys,
        sells=sells,
        quote_spent=quote_spent,
        quote_received=quote_received,
        fees=fees,
        final_base=base,
        final_quote=quote,
        end_price=end_price,
        equity=equity,
        return_pct=return_pct,
    )
    log.info(
        "Backtest %s candles=%s buys=%s sells=%s fees=%.2f equity=%.2f return=%.2f%%",
        symbol,
        result.candles,
        buys,
        sells,
        fees,
        equity,
        return_pct,
    )
    return result


def backtest_dca(
    ohlcv: Iterable[list],
    *,
    symbol: str,
    quote_amount: float,
    every_n_candles: int,
    fee_rate: float,
) -> BacktestResult:
    candles = list(ohlcv)
    if not candles:
        raise ValueError("No OHLCV data")
    quote_spent = fees = 0.0
    base = 0.0
    buys = 0
    for i, row in enumerate(candles):
        if i % every_n_candles != 0:
            continue
        close = float(row[4])
        fee = quote_amount * fee_rate
        spend = quote_amount - fee
        amount = spend / close
        base += amount
        quote_spent += quote_amount
        fees += fee
        buys += 1
    end_price = float(candles[-1][4])
    equity = base * end_price
    return_pct = ((equity / quote_spent) - 1.0) * 100.0 if quote_spent else 0.0
    return BacktestResult(
        symbol=symbol,
        candles=len(candles),
        buys=buys,
        sells=0,
        quote_spent=quote_spent,
        quote_received=0.0,
        fees=fees,
        final_base=base,
        final_quote=0.0,
        end_price=end_price,
        equity=equity,
        return_pct=return_pct,
    )
