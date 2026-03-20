"""
main.py — Trading Bot entry point.

Starts an APScheduler job that runs bot_cycle() on each candle close for the
timeframe set in config.json (e.g. 15m → every 15 minutes).  All configuration
is loaded from config.json; all credentials from .env.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from modules.compound_tracker import get_current_balance, get_portfolio_snapshot, update_balance_after_trade
from modules.data_feed import fetch_ohlcv, get_current_price
from modules.email_alerts import send_alert
from modules.order_executor import execute_buy, execute_sell
from modules.risk_manager import get_risk_parameters, is_daily_loss_limit_breached
from modules.signal_engine import generate_signal
from modules.trade_logger import get_today_trade_count, init_db, log_trade

# ── Bootstrap ──────────────────────────────────────────────────────────────────

load_dotenv()

CONFIG_FILE = Path("config.json")
PKT = pytz.timezone("Asia/Karachi")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Mutable bot state (in-memory, reset if process restarts) ──────────────────
# One position at a time (full balance).  active_pair = which market is open.
_state: dict = {
    "position_open":  False,
    "active_pair":    None,    # e.g. "ETH/USDT" while a position is open
    "buy_price":      None,
    "buy_quantity":   None,    # base-asset qty held (BTC, ETH, …)
    "buy_amount":     None,    # USDT spent on entry
    "stop_loss":      None,
    "take_profit":    None,
    "signal_at_buy":  None,
    "daily_halt":     False,   # True if daily loss limit hit today
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _cron_minute_for_timeframe(timeframe: str) -> str | int:
    """
    Map CCXT timeframe string to APScheduler cron `minute` expression.
    Aligns bot_cycle with each candle close for that interval.
    """
    tf = (timeframe or "15m").strip().lower()
    match tf:
        case "1m":
            return "*"
        case "5m":
            return "*/5"
        case "15m":
            return "0,15,30,45"
        case "30m":
            return "0,30"
        case "1h" | "60m":
            return 0
        case _:
            # Unknown timeframe — default to 15m cadence (safe for active trading)
            return "0,15,30,45"


def _pkt_now() -> str:
    return datetime.now(PKT).strftime("%Y-%m-%d %H:%M PKT")


def get_trading_pairs(config: dict) -> list[str]:
    """
    Return the list of markets to watch.
    Prefer `trading_pairs` (array); fall back to legacy `trading_pair` (string).
    """
    raw = config.get("trading_pairs")
    if isinstance(raw, list) and len(raw) > 0:
        return [str(p).strip() for p in raw if str(p).strip()]
    single = config.get("trading_pair", "BTC/USDT")
    return [single.strip()] if single else ["BTC/USDT"]


def _pairs_label(pairs: list[str]) -> str:
    """Short label for emails / logs (e.g. BTC+ETH+SOL+BNB)."""
    bases = [p.split("/")[0] for p in pairs]
    return "+".join(bases)


# ── Core bot cycle ─────────────────────────────────────────────────────────────

def bot_cycle() -> None:
    """Called once per candle close.  Full pipeline: data → signal → execute."""
    config = load_config()
    paper  = config.get("paper_trading", True)
    pairs  = get_trading_pairs(config)
    start  = config.get("starting_balance_usdt", 34.00)

    log.info("─── bot_cycle started (%s) — watching %s ───", _pkt_now(), ", ".join(pairs))

    try:
        # 1. Check daily halt flag
        if _state["daily_halt"]:
            log.info("Daily loss limit was hit — skipping until tomorrow.")
            return

        if is_daily_loss_limit_breached(start, config):
            log.warning("Daily loss limit breached. Bot halted for the rest of the day.")
            _state["daily_halt"] = True
            send_alert(
                "ERROR",
                {"error_message": "Daily loss limit breached. Bot halted until tomorrow."},
                get_portfolio_snapshot(start),
            )
            return

        portfolio = get_portfolio_snapshot(start)

        # ── 2–5: With an open position, only manage that pair (SELL / HOLD) ───
        if _state["position_open"] and _state.get("active_pair"):
            pair = _state["active_pair"]
            df    = fetch_ohlcv(pair, config["timeframe"], limit=100)
            price = get_current_price(pair)
            log.info(f"[{pair}] price ${price:,.2f}")

            sig = generate_signal(
                df,
                config,
                position_open=True,
                buy_price=_state["buy_price"],
                current_price=price,
            )
            log.info(
                f"[{pair}] Signal: {sig['signal']} — {sig['reason']} "
                f"(pattern={sig['pattern'] or 'None'}, RSI={sig['rsi'] or 0:.1f})"
            )

            if sig["signal"] == "SELL":
                order = execute_sell(pair, _state["buy_quantity"], price, paper=paper)

                pnl         = round(order["amount"] - _state["buy_amount"], 4)
                new_balance = update_balance_after_trade(start, pnl)

                alert_type = "SELL - PROFIT" if pnl >= 0 else "SELL - STOP LOSS"
                portfolio  = get_portfolio_snapshot(start)

                log_trade(alert_type, pair, order["price"], order["amount"],
                          sig["reason"], pnl, new_balance)

                send_alert(alert_type, {
                    "type":   alert_type,
                    "pair":   pair,
                    "price":  order["price"],
                    "amount": order["amount"],
                    "signal": sig["reason"],
                }, portfolio)

                log.info(f"SELL executed ({pair}): P&L=${pnl:+.4f}  new balance=${new_balance:.2f}")

                _state["position_open"] = False
                _state["active_pair"]   = None
                _state["buy_price"]     = None
                _state["buy_quantity"]  = None
                _state["buy_amount"]    = None
                _state["stop_loss"]     = None
                _state["take_profit"]   = None
                _state["signal_at_buy"] = None
            else:
                log.info(f"[{pair}] HOLD — position open, waiting for exit signal.")
            return

        # ── No position: scan pairs in order; first BUY wins ───────────────────
        for pair in pairs:
            df    = fetch_ohlcv(pair, config["timeframe"], limit=100)
            price = get_current_price(pair)
            sig = generate_signal(
                df,
                config,
                position_open=False,
                buy_price=None,
                current_price=price,
            )
            log.info(
                f"[{pair}] ${price:,.2f}  →  {sig['signal']} — {sig['reason']} "
                f"(RSI={sig['rsi'] or 0:.1f}, pat={sig['pattern'] or '—'})"
            )

            if sig["signal"] != "BUY":
                continue

            balance = get_current_balance(start)
            params  = get_risk_parameters(price, balance, config)
            amount  = params["position_size_usdt"]

            if amount < 10:
                log.warning("[%s] Balance too low to trade (%.2f USDT < $10 minimum).", pair, amount)
                continue

            order = execute_buy(pair, amount, price, paper=paper)

            _state["position_open"] = True
            _state["active_pair"]   = pair
            _state["buy_price"]     = order["price"]
            _state["buy_quantity"]  = order["quantity"]
            _state["buy_amount"]    = order["amount"]
            _state["stop_loss"]     = params["stop_loss_price"]
            _state["take_profit"]   = params["take_profit_price"]
            _state["signal_at_buy"] = sig["reason"]

            portfolio = get_portfolio_snapshot(start)

            log_trade("BUY", pair, order["price"], order["amount"],
                      sig["reason"], 0.0, portfolio["current"])

            send_alert("BUY", {
                "type":            "BUY",
                "pair":            pair,
                "price":           order["price"],
                "amount":          order["amount"],
                "signal":          sig["reason"],
                "stop_loss":       params["stop_loss_price"],
                "take_profit":     params["take_profit_price"],
                "stop_loss_pct":   params["stop_loss_pct"],
                "take_profit_pct": params["take_profit_pct"],
            }, portfolio)

            log.info(
                f"BUY executed ({pair}): ${amount:.2f} USDT @ ${order['price']:,.2f}  "
                f"SL=${params['stop_loss_price']:,.2f}  TP=${params['take_profit_price']:,.2f}"
            )
            return

        log.info("HOLD — no BUY signal on any watched pair.")

    except Exception as exc:
        log.exception("Unhandled error in bot_cycle: %s", exc)
        try:
            send_alert(
                "ERROR",
                {"error_message": f"{type(exc).__name__}: {exc}"},
                get_portfolio_snapshot(config.get("starting_balance_usdt", 34.00)),
            )
        except Exception:
            log.error("Also failed to send error email.")


# ── Daily summary (midnight PKT) ──────────────────────────────────────────────

def send_daily_summary() -> None:
    config  = load_config()
    start   = config.get("starting_balance_usdt", 34.00)
    pairs   = get_trading_pairs(config)
    snap    = get_portfolio_snapshot(start)
    today   = datetime.now(PKT).date().isoformat()
    trades  = get_today_trade_count()

    send_alert(
        "DAILY SUMMARY",
        {"date": today, "pair": _pairs_label(pairs)},
        {**snap, "trades_today": trades},
    )
    log.info("Daily summary sent. P&L today: $%+.4f", snap["pnl_today"])

    # Reset daily halt flag at midnight
    _state["daily_halt"] = False
    log.info("Daily halt flag reset.")


# ── Scheduler setup ───────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Trading Bot starting up ===")

    init_db()
    config = load_config()
    pairs  = get_trading_pairs(config)
    paper  = config.get("paper_trading", True)

    tf = config.get("timeframe", "15m")
    log.info("Pairs: %s | Timeframe: %s | Paper: %s", ", ".join(pairs), tf, paper)

    scheduler = BlockingScheduler(timezone=PKT)

    minute_cron = _cron_minute_for_timeframe(tf)
    scheduler.add_job(
        bot_cycle,
        trigger="cron",
        minute=minute_cron,
        id="bot_cycle",
        name=f"Bot cycle ({tf} candle close)",
        misfire_grace_time=120,
    )

    # Send daily summary at midnight PKT
    scheduler.add_job(
        send_daily_summary,
        trigger="cron",
        hour=0,
        minute=0,
        id="daily_summary",
        name="Daily summary email",
    )

    log.info("Scheduler started. Next cycle at each %s candle close (minute=%s).", tf, minute_cron)
    log.info("Press Ctrl+C to stop.")

    # Run once immediately on startup so we don't wait for the first boundary
    log.info("Running initial bot_cycle on startup …")
    bot_cycle()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
