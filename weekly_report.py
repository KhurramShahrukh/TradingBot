"""
weekly_report.py — End-of-week paper trading performance summary.

Reads all trades from trades.db and prints a formatted report:
  - Total trades, win rate, avg win, avg loss
  - Daily P&L breakdown
  - Signal breakdown (which patterns fired most)
  - Compounded balance progression
  - Go/No-go recommendation for live trading

Usage:
    python weekly_report.py
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

import pytz

DB_PATH = Path("trades.db")
PKT = pytz.timezone("Asia/Karachi")


def _load_trades() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_config() -> dict:
    try:
        with open("config.json") as f:
            return json.load(f)
    except Exception:
        return {"starting_balance_usdt": 34.0}


def _bar(value: float, max_val: float, width: int = 20, char: str = "█") -> str:
    if max_val == 0:
        return ""
    filled = int(abs(value) / max_val * width)
    return char * filled


def _sep(char: str = "─", width: int = 55) -> str:
    return char * width


def main() -> None:
    trades = _load_trades()
    config = _load_config()
    starting = config.get("starting_balance_usdt", 34.0)

    now_pkt = datetime.now(PKT).strftime("%Y-%m-%d %H:%M PKT")

    print(_sep("═"))
    print("  TRADING BOT — WEEKLY PAPER TRADING REPORT")
    print(f"  Generated: {now_pkt}")
    print(_sep("═"))

    if not trades:
        print("\n  No trades found in trades.db.")
        print("  The bot may not have fired any BUY signals yet.")
        print("  This is normal if BTC RSI has stayed above 35 all week.")
        print("\n  Tips:")
        print("  - Lower rsi_oversold in config.json from 35 → 40 to see more signals")
        print("  - Check logs/bot.log to confirm the bot is running hourly")
        print(_sep("═"))
        return

    # ── Separate BUYs from SELLs ──────────────────────────────────────────────
    sells = [t for t in trades if "SELL" in t["type"]]
    buys  = [t for t in trades if t["type"] == "BUY"]

    wins   = [t for t in sells if t["pnl"] > 0]
    losses = [t for t in sells if t["pnl"] < 0]
    breakevens = [t for t in sells if t["pnl"] == 0]

    total_completed = len(sells)
    win_rate = (len(wins) / total_completed * 100) if total_completed else 0
    total_pnl = sum(t["pnl"] for t in sells)
    avg_win   = (sum(t["pnl"] for t in wins)   / len(wins))   if wins   else 0
    avg_loss  = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0

    current_balance = round(starting + total_pnl, 2)
    total_return_pct = (total_pnl / starting * 100) if starting else 0

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n  OVERALL PERFORMANCE")
    print(_sep())
    print(f"  Starting balance:   ${starting:.2f}")
    print(f"  Current balance:    ${current_balance:.2f}")
    print(f"  Total P&L:          ${total_pnl:+.4f}  ({total_return_pct:+.2f}%)")
    print(f"  Completed trades:   {total_completed}")
    print(f"  Open positions:     {len(buys) - len(sells)}")
    print(f"  Win rate:           {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L / {len(breakevens)}B)")
    print(f"  Avg win:            ${avg_win:+.4f}")
    print(f"  Avg loss:           ${avg_loss:+.4f}")
    if avg_loss != 0:
        rr = abs(avg_win / avg_loss)
        print(f"  Risk/reward ratio:  {rr:.2f}:1")

    # ── Daily breakdown ───────────────────────────────────────────────────────
    daily_pnl: dict[str, float] = defaultdict(float)
    daily_count: dict[str, int] = defaultdict(int)

    for t in sells:
        day = t["timestamp"][:10]
        daily_pnl[day]   += t["pnl"]
        daily_count[day] += 1

    if daily_pnl:
        print(f"\n  DAILY P&L BREAKDOWN")
        print(_sep())
        max_abs = max(abs(v) for v in daily_pnl.values()) or 1
        for day in sorted(daily_pnl):
            pnl   = daily_pnl[day]
            count = daily_count[day]
            bar   = _bar(pnl, max_abs, width=15, char="+" if pnl >= 0 else "-")
            sign  = "▲" if pnl >= 0 else "▼"
            print(f"  {day}  {sign} ${pnl:+.4f}  [{bar:<15}]  ({count} trade{'s' if count != 1 else ''})")

    # ── Signal breakdown ──────────────────────────────────────────────────────
    signal_counts: dict[str, int] = defaultdict(int)
    for t in trades:
        sig = t.get("signal") or "Unknown"
        # Normalise multi-part signals to first component
        key = sig.split("+")[0].strip()
        signal_counts[key] += 1

    if signal_counts:
        print(f"\n  SIGNAL BREAKDOWN  (all trade events)")
        print(_sep())
        for sig, cnt in sorted(signal_counts.items(), key=lambda x: -x[1]):
            print(f"  {sig:<40} {cnt:>3}x")

    # ── Sell reason breakdown ─────────────────────────────────────────────────
    stop_losses    = [t for t in sells if "STOP" in t["type"]]
    take_profits   = [t for t in sells if "PROFIT" in t["type"]]

    print(f"\n  SELL REASON BREAKDOWN")
    print(_sep())
    print(f"  Take-profit hits:   {len(take_profits)}")
    print(f"  Stop-loss hits:     {len(stop_losses)}")

    # ── Balance curve (last 10 trade snapshots) ───────────────────────────────
    balance_snapshots = [(t["timestamp"][:16], t["balance"]) for t in trades[-10:]]
    if balance_snapshots:
        print(f"\n  BALANCE CURVE  (last {len(balance_snapshots)} trade events)")
        print(_sep())
        for ts, bal in balance_snapshots:
            diff = bal - starting
            sign = "▲" if diff >= 0 else "▼"
            print(f"  {ts}   ${bal:.2f}  {sign} ${diff:+.2f}")

    # ── Go / No-go assessment ─────────────────────────────────────────────────
    print(f"\n  GO / NO-GO ASSESSMENT")
    print(_sep())

    checks = []

    # 1. Win rate >= 55%
    if total_completed >= 5:
        ok = win_rate >= 55
        checks.append((ok, f"Win rate {win_rate:.1f}% {'≥' if ok else '<'} 55% target"))
    else:
        checks.append((None, f"Too few trades ({total_completed}) to assess win rate — keep testing"))

    # 2. No runaway losses — biggest single loss < 2%
    if losses:
        worst_loss_pct = abs(min(t["pnl"] for t in losses)) / starting * 100
        ok = worst_loss_pct < 2.0
        checks.append((ok, f"Worst single loss {worst_loss_pct:.2f}% {'<' if ok else '≥'} 2% threshold"))
    else:
        checks.append((True, "No losses recorded"))

    # 3. Total P&L positive
    ok = total_pnl >= 0
    checks.append((ok, f"Total P&L ${total_pnl:+.4f} is {'positive' if ok else 'negative'}"))

    # 4. Risk/reward > 1:1
    if avg_loss != 0 and avg_win != 0:
        rr = abs(avg_win / avg_loss)
        ok = rr >= 1.0
        checks.append((ok, f"Risk/reward {rr:.2f}:1 {'≥' if ok else '<'} 1:1 minimum"))

    # 5. Daily loss limit never breached (checked via emails/log — can only hint here)
    checks.append((None, "Confirm no [ERROR] daily-halt emails were received"))

    any_fail   = any(c[0] is False for c in checks)
    any_unknown= any(c[0] is None for c in checks)

    for ok, msg in checks:
        icon = "✓" if ok is True else ("?" if ok is None else "✗")
        print(f"  [{icon}] {msg}")

    print()
    if any_fail:
        print("  VERDICT: NOT READY — fix failing checks before going live.")
    elif any_unknown:
        print("  VERDICT: NEEDS MORE DATA — continue paper testing.")
    else:
        print("  VERDICT: READY — all checks pass.")
        print("         Set paper_trading: false in config.json to go live.")

    print(_sep("═"))
    print("  Run this report any time:  python weekly_report.py")
    print(_sep("═"))


if __name__ == "__main__":
    main()
