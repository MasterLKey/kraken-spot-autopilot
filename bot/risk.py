from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bot.journal import Journal
from bot.logging_setup import get_logger

log = get_logger("bot.risk")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(
        self,
        journal: Journal,
        *,
        max_daily_loss_quote: float,
        max_position_quote: float,
        max_order_quote: float,
        kill_switch_file: Path,
    ) -> None:
        self.journal = journal
        self.max_daily_loss_quote = max_daily_loss_quote
        self.max_position_quote = max_position_quote
        self.max_order_quote = max_order_quote
        self.kill_switch_file = kill_switch_file
        self._manual_halt = False

    def halt(self, reason: str = "manual") -> None:
        self._manual_halt = True
        self.kill_switch_file.write_text(reason, encoding="utf-8")
        self.journal.log_event("kill_switch", f"halted: {reason}", level="WARNING")
        log.warning("Kill switch engaged: %s", reason)

    def clear_halt(self) -> None:
        self._manual_halt = False
        if self.kill_switch_file.exists():
            self.kill_switch_file.unlink()
        self.journal.log_event("kill_switch", "cleared")
        log.info("Kill switch cleared")

    def is_halted(self) -> bool:
        return self._manual_halt or self.kill_switch_file.exists()

    def check_order(
        self,
        *,
        symbol: str,
        side: str,
        quote_notional: float,
        mark_price: float,
    ) -> RiskDecision:
        if self.is_halted():
            return RiskDecision(False, "kill switch active")

        if quote_notional <= 0:
            return RiskDecision(False, "non-positive notional")

        if quote_notional > self.max_order_quote:
            return RiskDecision(
                False,
                f"order {quote_notional:.2f} exceeds max_order_quote {self.max_order_quote:.2f}",
            )

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self.journal.get_daily_pnl(day)
        if daily <= -abs(self.max_daily_loss_quote):
            self.halt(f"daily loss {daily:.2f} hit limit")
            return RiskDecision(False, "daily loss limit reached")

        base, quote_spent = self.journal.position_cost_basis(symbol)
        position_quote = max(quote_spent, base * mark_price) if mark_price > 0 else quote_spent

        if side == "buy" and (position_quote + quote_notional) > self.max_position_quote:
            return RiskDecision(
                False,
                f"position would be {position_quote + quote_notional:.2f} > max {self.max_position_quote:.2f}",
            )

        return RiskDecision(True, "ok")
