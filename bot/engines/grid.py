from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from bot.exchange.kraken import KrakenClient, OrderResult
from bot.journal import Fill, Journal
from bot.logging_setup import get_logger
from bot.notify import Notifier
from bot.paper import PaperBroker
from bot.risk import RiskManager

log = get_logger("bot.grid")


@dataclass
class GridLevel:
    price: float
    side: str  # buy levels below mid, sell above
    amount: float
    filled: bool = False
    order_id: Optional[str] = None


@dataclass
class GridConfig:
    symbol: str
    lower: float
    upper: float
    levels: int
    quote_per_level: float
    base_reserve: float = 0.0


@dataclass
class GridState:
    levels: list[GridLevel] = field(default_factory=list)


class GridEngine:
    """Simple spot geometric grid: buys below mid, sells above mid."""

    def __init__(
        self,
        cfg: GridConfig,
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
        self.state = GridState()
        self._load_or_build()

    def _load_or_build(self) -> None:
        raw = self.journal.get_state("grid_levels")
        if raw:
            data = json.loads(raw)
            self.state.levels = [GridLevel(**item) for item in data]
            log.info("Loaded %s grid levels from journal", len(self.state.levels))
            return
        self._build_levels()
        self._persist()

    def _build_levels(self) -> None:
        if self.cfg.lower <= 0 or self.cfg.upper <= 0 or self.cfg.upper <= self.cfg.lower:
            raise ValueError("Grid requires GRID_LOWER_PRICE < GRID_UPPER_PRICE and both > 0")
        if self.cfg.levels < 2:
            raise ValueError("GRID_LEVELS must be >= 2")

        # Evenly spaced prices
        step = (self.cfg.upper - self.cfg.lower) / (self.cfg.levels - 1)
        mid = (self.cfg.lower + self.cfg.upper) / 2.0
        levels: list[GridLevel] = []
        for i in range(self.cfg.levels):
            price = self.cfg.lower + step * i
            if abs(price - mid) < step * 0.25:
                continue  # skip near mid
            side = "buy" if price < mid else "sell"
            amount = self.cfg.quote_per_level / price
            levels.append(GridLevel(price=price, side=side, amount=amount))
        self.state.levels = levels
        log.info(
            "Built grid %s levels on %s [%.2f, %.2f]",
            len(levels),
            self.cfg.symbol,
            self.cfg.lower,
            self.cfg.upper,
        )

    def _persist(self) -> None:
        payload = [
            {
                "price": lvl.price,
                "side": lvl.side,
                "amount": lvl.amount,
                "filled": lvl.filled,
                "order_id": lvl.order_id,
            }
            for lvl in self.state.levels
        ]
        self.journal.set_state("grid_levels", json.dumps(payload))

    def reset(self) -> None:
        self._build_levels()
        self._persist()

    def _record_fill(self, order: OrderResult, note: str) -> None:
        price = float(order.price or 0)
        cost = float(order.cost or (order.amount * price))
        fee = float(order.raw.get("fee") or cost * self.fee_rate)
        fill = Fill(
            ts=time.time(),
            mode=self.mode,
            strategy="grid",
            symbol=self.cfg.symbol,
            side=order.side,
            order_type=order.type,
            amount=order.amount,
            price=price,
            cost=cost,
            fee=fee,
            order_id=order.id,
            paper=order.paper,
            note=note,
        )
        self.journal.log_fill(fill)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Approximate realized: sells add proceeds - fee; buys subtract fee only here
        if order.side == "sell":
            self.journal.add_daily_pnl(day, cost - fee)
        else:
            self.journal.add_daily_pnl(day, -fee)
        msg = (
            f"GRID {self.mode.upper()} {order.side} {self.cfg.symbol}\n"
            f"amount={order.amount:.8f} price={price:.2f} cost={cost:.2f}"
        )
        log.info(msg.replace("\n", " | "))
        self.notifier.send(msg)

    def tick(self) -> list[OrderResult]:
        ticker = self.client.fetch_ticker(self.cfg.symbol)
        fills: list[OrderResult] = []

        for lvl in self.state.levels:
            if lvl.filled:
                continue

            quote_notional = lvl.amount * lvl.price
            decision = self.risk.check_order(
                symbol=self.cfg.symbol,
                side=lvl.side,
                quote_notional=quote_notional,
                mark_price=ticker.last,
            )
            if not decision.allowed:
                log.debug("Grid level %.2f blocked: %s", lvl.price, decision.reason)
                continue

            order: Optional[OrderResult] = None
            if self.mode == "paper":
                assert self.paper is not None
                order = self.paper.limit_fill_if_touched(
                    self.cfg.symbol, lvl.side, lvl.amount, lvl.price, ticker
                )
            else:
                # Live: place resting limit if not already placed; check fills via open orders absence
                if not lvl.order_id:
                    try:
                        placed = self.client.create_limit_order(
                            self.cfg.symbol, lvl.side, lvl.amount, lvl.price
                        )
                        lvl.order_id = placed.id
                        self._persist()
                        log.info("Placed live grid %s @ %.2f id=%s", lvl.side, lvl.price, placed.id)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Failed to place grid order @ %.2f: %s", lvl.price, exc)
                    continue

                open_ids = {str(o["id"]) for o in self.client.fetch_open_orders(self.cfg.symbol)}
                if lvl.order_id not in open_ids:
                    # Treat as filled (simplified — production would fetch order)
                    order = OrderResult(
                        id=lvl.order_id,
                        symbol=self.cfg.symbol,
                        side=lvl.side,
                        type="limit",
                        amount=lvl.amount,
                        price=lvl.price,
                        cost=lvl.amount * lvl.price,
                        status="closed",
                        raw={"fee": lvl.amount * lvl.price * self.fee_rate},
                        paper=False,
                    )

            if order is None:
                continue

            lvl.filled = True
            self._record_fill(order, note=f"grid level {lvl.price:.2f}")
            fills.append(order)

            # Flip the level to the other side after fill (classic grid recycle)
            mid = (self.cfg.lower + self.cfg.upper) / 2.0
            new_side = "sell" if order.side == "buy" else "buy"
            # Place recycled level slightly across mid relative to fill
            if new_side == "sell":
                new_price = min(self.cfg.upper, max(mid, lvl.price * 1.002))
            else:
                new_price = max(self.cfg.lower, min(mid, lvl.price * 0.998))
            lvl.side = new_side
            lvl.price = new_price
            lvl.amount = self.cfg.quote_per_level / new_price
            lvl.filled = False
            lvl.order_id = None

        self._persist()
        return fills
