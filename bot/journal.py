from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    amount REAL NOT NULL,
    price REAL NOT NULL,
    cost REAL NOT NULL,
    fee REAL NOT NULL,
    order_id TEXT,
    paper INTEGER NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    day TEXT PRIMARY KEY,
    realized_quote REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Fill:
    ts: float
    mode: str
    strategy: str
    symbol: str
    side: str
    order_type: str
    amount: float
    price: float
    cost: float
    fee: float
    order_id: str
    paper: bool
    note: str = ""


class Journal:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def log_fill(self, fill: Fill) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO fills (
                ts, mode, strategy, symbol, side, order_type,
                amount, price, cost, fee, order_id, paper, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.ts,
                fill.mode,
                fill.strategy,
                fill.symbol,
                fill.side,
                fill.order_type,
                fill.amount,
                fill.price,
                fill.cost,
                fill.fee,
                fill.order_id,
                1 if fill.paper else 0,
                fill.note,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def log_event(self, kind: str, message: str, *, level: str = "INFO", payload: str = "") -> None:
        self._conn.execute(
            "INSERT INTO events (ts, level, kind, message, payload) VALUES (?, ?, ?, ?, ?)",
            (time.time(), level, kind, message, payload),
        )
        self._conn.commit()

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def add_daily_pnl(self, day: str, delta: float) -> float:
        self._conn.execute(
            """
            INSERT INTO daily_pnl (day, realized_quote) VALUES (?, ?)
            ON CONFLICT(day) DO UPDATE SET realized_quote = realized_quote + excluded.realized_quote
            """,
            (day, delta),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT realized_quote FROM daily_pnl WHERE day = ?", (day,)).fetchone()
        return float(row["realized_quote"])

    def get_daily_pnl(self, day: str) -> float:
        row = self._conn.execute("SELECT realized_quote FROM daily_pnl WHERE day = ?", (day,)).fetchone()
        return float(row["realized_quote"]) if row else 0.0

    def iter_fills(self) -> Iterable[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM fills ORDER BY ts ASC")

    def position_cost_basis(self, symbol: str) -> tuple[float, float]:
        """Return (base_amount, quote_spent_net) for buys minus sells."""
        rows = self._conn.execute(
            "SELECT side, amount, cost FROM fills WHERE symbol = ?",
            (symbol,),
        ).fetchall()
        base = 0.0
        quote = 0.0
        for row in rows:
            if row["side"] == "buy":
                base += float(row["amount"])
                quote += float(row["cost"])
            else:
                base -= float(row["amount"])
                quote -= float(row["cost"])
        return base, quote

    def export_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(self.iter_fills())
        fields = [
            "id",
            "ts",
            "mode",
            "strategy",
            "symbol",
            "side",
            "order_type",
            "amount",
            "price",
            "cost",
            "fee",
            "order_id",
            "paper",
            "note",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in fields})
        return path

    def summary(self) -> dict[str, Any]:
        fill_count = self._conn.execute("SELECT COUNT(*) AS c FROM fills").fetchone()["c"]
        buy_cost = self._conn.execute(
            "SELECT COALESCE(SUM(cost), 0) AS s FROM fills WHERE side = 'buy'"
        ).fetchone()["s"]
        sell_cost = self._conn.execute(
            "SELECT COALESCE(SUM(cost), 0) AS s FROM fills WHERE side = 'sell'"
        ).fetchone()["s"]
        fees = self._conn.execute("SELECT COALESCE(SUM(fee), 0) AS s FROM fills").fetchone()["s"]
        return {
            "fills": int(fill_count),
            "buy_cost": float(buy_cost),
            "sell_proceeds": float(sell_cost),
            "fees": float(fees),
        }
