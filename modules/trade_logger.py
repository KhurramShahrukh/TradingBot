import sqlite3
from datetime import datetime, date
from pathlib import Path

import pytz

DB_PATH = Path("trades.db")
PKT = pytz.timezone("Asia/Karachi")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the trades table if it does not already exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                type      TEXT    NOT NULL,
                pair      TEXT    NOT NULL,
                price     REAL    NOT NULL,
                amount    REAL    NOT NULL,
                signal    TEXT,
                pnl       REAL    DEFAULT 0.0,
                balance   REAL    NOT NULL
            )
        """)
        conn.commit()


def log_trade(
    trade_type: str,
    pair: str,
    price: float,
    amount: float,
    signal: str,
    pnl: float,
    balance: float,
) -> int:
    """
    Insert one trade record. Returns the new row id.

    trade_type : "BUY" | "SELL - PROFIT" | "SELL - STOP LOSS"
    pnl        : realised profit/loss in USDT (0.0 for BUY rows)
    balance    : account balance AFTER this trade
    """
    ts = datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S")
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO trades (timestamp, type, pair, price, amount, signal, pnl, balance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, trade_type, pair, round(price, 2), round(amount, 2), signal, round(pnl, 4), round(balance, 2)),
        )
        conn.commit()
        return cur.lastrowid


def get_today_pnl() -> float:
    """Return total realised P&L (USDT) for the current PKT calendar day."""
    today = datetime.now(PKT).date().isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0.0) AS total FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()
    return float(row["total"])


def get_today_trade_count() -> int:
    """Return number of trades executed today (PKT)."""
    today = datetime.now(PKT).date().isoformat()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()
    return int(row["cnt"])


def get_all_trades() -> list[dict]:
    """Return every trade record as a list of dicts, newest first."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_total_pnl() -> float:
    """Return cumulative P&L across all time."""
    with _get_conn() as conn:
        row = conn.execute("SELECT COALESCE(SUM(pnl), 0.0) AS total FROM trades").fetchone()
    return float(row["total"])


if __name__ == "__main__":
    init_db()
    rid = log_trade(
        trade_type="BUY",
        pair="BTC/USDT",
        price=67_000.00,
        amount=35.00,
        signal="Bullish Engulfing + RSI 34",
        pnl=0.0,
        balance=35.00,
    )
    print(f"Logged BUY trade, row id={rid}")
    print(f"Today P&L:  ${get_today_pnl():.2f}")
    print(f"Total P&L:  ${get_total_pnl():.2f}")
    print(f"All trades: {get_all_trades()}")
