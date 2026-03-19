"""
main.py — Trading Bot entry point.

Starts an APScheduler job that runs bot_cycle() at the top of every hour
(i.e., on each 1-hour candle close).  All configuration is loaded from
config.json; all credentials from .env.
"""

import json
import logging
import sys
import time
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
_state: dict = {
    "position_open":  False,
    "buy_price":      None,
    "buy_quantity":   None,    # BTC quantity held
    "buy_amount":     None,    # USDT spent on entry
    "stop_loss":      None,
    "take_profit":    None,
    "signal_at_buy":  None,
    "daily_halt":     False,   # True if daily loss limit hit today
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _pkt_now() -> str:
    return datetime.now(PKT).strftime("%Y-%m-%d %H:%M PKT")


# ── Core bot cycle ─────────────────────────────────────────────────────────────

def bot_cycle() -> None:
    """Called once per candle close.  Full pipeline: data → signal → execute."""
    config = load_config()
    paper  = config.get("paper_trading", True)
    pair   = config.get("trading_pair",  "BTC/USDT")
    start  = config.get("starting_balance_usdt", 35.00)

    log.info("─── bot_cycle started (%s) ───", _pkt_now())

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

        # 2. Fetch market data
        df    = fetch_ohlcv(pair, config["timeframe"], limit=100)
        price = get_current_price(pair)
        log.info("Current %s price: $%,.2f", pair, price)

        # 3. Generate signal
        sig = generate_signal(
            df,
            config,
            position_open=_state["position_open"],
            buy_price=_state["buy_price"],
            current_price=price,
        )
        log.info("Signal: %s — %s (pattern=%s, RSI=%.1f)",
                 sig["signal"], sig["reason"],
                 sig["pattern"] or "None",
                 sig["rsi"] or 0)

        portfolio = get_portfolio_snapshot(start)

        # 4. Execute BUY
        if sig["signal"] == "BUY" and not _state["position_open"]:
            balance = get_current_balance(start)
            params  = get_risk_parameters(price, balance, config)
            amount  = params["position_size_usdt"]

            if amount < 10:
                log.warning("Balance too low to trade (%.2f USDT < $10 minimum).", amount)
                return

            order = execute_buy(pair, amount, price, paper=paper)

            _state["position_open"] = True
            _state["buy_price"]     = order["price"]
            _state["buy_quantity"]  = order["quantity"]
            _state["buy_amount"]    = order["amount"]
            _state["stop_loss"]     = params["stop_loss_price"]
            _state["take_profit"]   = params["take_profit_price"]
            _state["signal_at_buy"] = sig["reason"]

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

            log.info("BUY executed: $%.2f USDT @ $%,.2f  SL=$%,.2f  TP=$%,.2f",
                     amount, order["price"],
                     params["stop_loss_price"], params["take_profit_price"])

        # 5. Execute SELL
        elif sig["signal"] == "SELL" and _state["position_open"]:
            order = execute_sell(pair, _state["buy_quantity"], price, paper=paper)

            pnl        = round(order["amount"] - _state["buy_amount"], 4)
            new_balance= update_balance_after_trade(start, pnl)

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

            log.info("SELL executed: P&L=$%+.4f  new balance=$%.2f", pnl, new_balance)

            # Reset position state
            _state["position_open"] = False
            _state["buy_price"]     = None
            _state["buy_quantity"]  = None
            _state["buy_amount"]    = None
            _state["stop_loss"]     = None
            _state["take_profit"]   = None
            _state["signal_at_buy"] = None

        else:
            log.info("HOLD — no action taken.")

    except Exception as exc:
        log.exception("Unhandled error in bot_cycle: %s", exc)
        try:
            send_alert(
                "ERROR",
                {"error_message": f"{type(exc).__name__}: {exc}"},
                get_portfolio_snapshot(config.get("starting_balance_usdt", 35.00)),
            )
        except Exception:
            log.error("Also failed to send error email.")


# ── Daily summary (midnight PKT) ──────────────────────────────────────────────

def send_daily_summary() -> None:
    config  = load_config()
    start   = config.get("starting_balance_usdt", 35.00)
    snap    = get_portfolio_snapshot(start)
    today   = datetime.now(PKT).date().isoformat()
    trades  = get_today_trade_count()

    send_alert("DAILY SUMMARY", {"date": today}, {**snap, "trades_today": trades})
    log.info("Daily summary sent. P&L today: $%+.4f", snap["pnl_today"])

    # Reset daily halt flag at midnight
    _state["daily_halt"] = False
    log.info("Daily halt flag reset.")


# ── Scheduler setup ───────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Trading Bot starting up ===")

    init_db()
    config = load_config()
    pair   = config.get("trading_pair", "BTC/USDT")
    paper  = config.get("paper_trading", True)

    log.info("Pair: %s | Timeframe: %s | Paper: %s", pair, config["timeframe"], paper)

    scheduler = BlockingScheduler(timezone=PKT)

    # Run bot cycle at the top of every hour (candle close for 1h chart)
    scheduler.add_job(
        bot_cycle,
        trigger="cron",
        minute=0,
        id="bot_cycle",
        name="Bot cycle (1h candle close)",
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

    log.info("Scheduler started. Waiting for next full hour …")
    log.info("Press Ctrl+C to stop.")

    # Run once immediately on startup so we don't have to wait an hour
    log.info("Running initial bot_cycle on startup …")
    bot_cycle()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
