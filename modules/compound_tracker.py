import json
from pathlib import Path

from modules.trade_logger import get_total_pnl, get_today_pnl

STATE_FILE = Path("compound_state.json")


def _load_state(starting_balance: float) -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    state = {"balance": round(starting_balance, 2), "starting": round(starting_balance, 2)}
    _save_state(state)
    return state


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_current_balance(starting_balance: float) -> float:
    """Return the current account balance derived from starting capital + all P&L."""
    state = _load_state(starting_balance)
    total_pnl = get_total_pnl()
    return round(state["starting"] + total_pnl, 2)


def update_balance_after_trade(starting_balance: float, pnl: float) -> float:
    """
    Record a completed trade's P&L and return the updated balance.
    The balance is always derived from starting + cumulative P&L so it
    never drifts from the SQLite source of truth.
    """
    state = _load_state(starting_balance)
    new_balance = round(state["starting"] + get_total_pnl() + pnl, 2)
    state["balance"] = new_balance
    _save_state(state)
    return new_balance


def get_portfolio_snapshot(starting_balance: float) -> dict:
    """
    Return a portfolio summary dict suitable for email alerts and logging.

    Keys:
        starting    — original capital
        current     — current balance
        pnl_today   — today's realised P&L
        total_pnl   — all-time realised P&L
        total_pct   — all-time return %
    """
    state   = _load_state(starting_balance)
    start   = state["starting"]
    current = get_current_balance(starting_balance)
    pnl_day = get_today_pnl()
    pnl_tot = get_total_pnl()
    pct     = (pnl_tot / start * 100) if start else 0.0

    return {
        "starting":  round(start,   2),
        "current":   round(current, 2),
        "pnl_today": round(pnl_day, 4),
        "total_pnl": round(pnl_tot, 4),
        "total_pct": round(pct,     4),
    }


if __name__ == "__main__":
    STARTING = 34.00

    snap = get_portfolio_snapshot(STARTING)
    print("Portfolio snapshot:")
    for k, v in snap.items():
        print(f"  {k}: {v}")

    print(f"\nCurrent balance: ${get_current_balance(STARTING):.2f}")
