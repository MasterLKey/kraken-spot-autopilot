from __future__ import annotations

import httpx

from bot.logging_setup import get_logger

log = get_logger("bot.notify")


class Notifier:
    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self.token = token.strip()
        self.chat_id = chat_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, message: str) -> None:
        if not self.enabled:
            log.debug("Telegram disabled; skip notify: %s", message)
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json={"chat_id": self.chat_id, "text": message})
                resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — never crash the bot on notify failure
            log.warning("Telegram notify failed: %s", exc)
