"""
main.py — Trading Bot entry point.

Starts an APScheduler job that runs bot_cycle() on each candle close for the
timeframe set in config.json (e.g. 5m → every 5 minutes).  All configuration
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
from modules.data_feed import fetch_ohlcv, get_balance_usdt, get_current_price
from modules.email_alerts import send_alert
from modules.order_executor import execute_buy, execute_sell
from modules.risk_manager import get_risk_parameters, is_daily_loss_limit_breached
from modules.signal_engine import generate_signal
from modules.trade_logger import get_today_trade_count, init_db, log_trade

# ── Bootstrap ──────────────────────────────────────────────────────────────────

load_dotenv()

CONFIG_FILE = Path("config.json")
PKT = pytz.timezone("Asia/Karachi")

Path("logs").mkdir(parents=True, exist_ok=True)

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
    "stop_loss":         None,
    "take_profit":       None,
    "stop_loss_pct":     None,
    "take_profit_pct":   None,
    "max_loss_pct":      None,
    "max_loss_price":    None,
    "signal_at_buy":     None,
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
    tf = (timeframe or "5m").strip().lower()
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
            # Unknown timeframe — default to 5m cadence
            return "*/5"


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
    """Short label for emails (e.g. BTC+ETH+…+32 markets)."""
    bases = [p.split("/")[0] for p in pairs]
    if len(bases) <= 6:
        return "+".join(bases)
    return "+".join(bases[:6]) + f"+…({len(bases)} total)"


# ── Core bot cycle ─────────────────────────────────────────────────────────────

def bot_cycle() -> None:
    """Called once per candle close.  Full pipeline: data → signal → execute."""
    config = load_config()
    paper  = config.get("paper_trading", True)
    pairs  = get_trading_pairs(config)
    start  = config.get("starting_balance_usdt", 34.00)

    log.info("─── bot_cycle started (%s) — watching %d pairs ───", _pkt_now(), len(pairs))

    live_usdt: float | None = None
    if not paper:
        try:
            live_usdt = get_balance_usdt()
            log.info("Live spot USDT (free): $%.2f", live_usdt)
        except Exception as exc:
            log.error("Live mode: could not fetch USDT balance: %s", exc)
            try:
                send_alert(
                    "ERROR",
                    {"error_message": f"Live mode: USDT balance fetch failed: {exc}"},
                    get_portfolio_snapshot(start),
                )
            except Exception:
                log.error("Also failed to send balance error email.")
            return

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
                get_portfolio_snapshot(start, live_usdt=live_usdt),
            )
            return

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
                entry_stop_loss_pct=_state.get("stop_loss_pct"),
                entry_take_profit_pct=_state.get("take_profit_pct"),
                entry_max_loss_pct=_state.get("max_loss_pct"),
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
                if not paper:
                    try:
                        live_usdt = get_balance_usdt()
                    except Exception as exc:
                        log.warning("Could not refresh USDT after SELL: %s", exc)
                portfolio  = get_portfolio_snapshot(start, live_usdt=live_usdt)

                log_trade(
                    alert_type,
                    pair,
                    order["price"],
                    order["amount"],
                    sig["reason"],
                    pnl,
                    portfolio["current"] if not paper else new_balance,
                )

                send_alert(alert_type, {
                    "type":      alert_type,
                    "pair":      pair,
                    "price":     order["price"],
                    "amount":    order["amount"],
                    "signal":    sig["reason"],
                    "timeframe": config.get("timeframe", "5m"),
                }, portfolio)

                log.info(f"SELL executed ({pair}): P&L=${pnl:+.4f}  new balance=${new_balance:.2f}")

                _state["position_open"] = False
                _state["active_pair"]   = None
                _state["buy_price"]     = None
                _state["buy_quantity"]  = None
                _state["buy_amount"]    = None
                _state["stop_loss"]       = None
                _state["take_profit"]     = None
                _state["stop_loss_pct"]   = None
                _state["take_profit_pct"] = None
                _state["max_loss_pct"]    = None
                _state["max_loss_price"]  = None
                _state["signal_at_buy"]   = None
            else:
                log.info(f"[{pair}] HOLD — position open, waiting for exit signal.")
            return

        # ── No position: scan pairs in order; first BUY wins ───────────────────
        for pair in pairs:
            try:
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

                if not paper:
                    try:
                        live_usdt = get_balance_usdt()
                    except Exception as bal_exc:
                        log.warning("Skipping %s: could not fetch USDT balance: %s", pair, bal_exc)
                        continue

                balance = live_usdt if not paper else get_current_balance(start)
                params  = get_risk_parameters(
                    price, balance, config, satisfied_legs=sig.get("buy_legs")
                )
                amount  = params["position_size_usdt"]

                if amount < 10:
                    log.warning("[%s] Balance too low to trade (%.2f USDT < $10 minimum).", pair, amount)
                    continue

                order = execute_buy(pair, amount, price, paper=paper)

                if not paper:
                    try:
                        live_usdt = get_balance_usdt()
                    except Exception as exc:
                        log.warning("Could not refresh USDT after BUY: %s", exc)

                _state["position_open"] = True
                _state["active_pair"]   = pair
                _state["buy_price"]     = order["price"]
                _state["buy_quantity"]  = order["quantity"]
                _state["buy_amount"]    = order["amount"]
                _state["stop_loss"]       = params["stop_loss_price"]
                _state["take_profit"]     = params.get("take_profit_price")
                _state["stop_loss_pct"]   = params["stop_loss_pct"]
                _state["take_profit_pct"] = params.get("take_profit_pct")
                _state["max_loss_pct"]    = params.get("max_loss_pct")
                _state["max_loss_price"]  = params.get("max_loss_price")
                _state["signal_at_buy"]   = sig["reason"]

                portfolio = get_portfolio_snapshot(start, live_usdt=live_usdt)

                log_trade("BUY", pair, order["price"], order["amount"],
                          sig["reason"], 0.0, portfolio["current"])

                buy_alert = {
                    "type":          "BUY",
                    "pair":          pair,
                    "price":         order["price"],
                    "amount":        order["amount"],
                    "signal":        sig["reason"],
                    "stop_loss":     params["stop_loss_price"],
                    "stop_loss_pct": params["stop_loss_pct"],
                    "timeframe":     config.get("timeframe", "5m"),
                }
                if params.get("take_profit_price") is not None:
                    buy_alert["take_profit"] = params["take_profit_price"]
                    buy_alert["take_profit_pct"] = params["take_profit_pct"]
                if params.get("max_loss_pct") is not None:
                    buy_alert["max_loss"]     = params["max_loss_price"]
                    buy_alert["max_loss_pct"] = params["max_loss_pct"]
                    buy_alert["mode"] = "hold_until_profit"
                send_alert("BUY", buy_alert, portfolio)

                tp_log = (
                    f"TP=${params['take_profit_price']:,.2f}"
                    if params.get("take_profit_price") is not None
                    else "TP=— (ride until bearish reversal)"
                )
                ml_log = (
                    f"  MaxLoss=${params['max_loss_price']:,.2f} ({params['max_loss_pct']}%)"
                    if params.get("max_loss_price") is not None
                    else ""
                )
                log.info(
                    f"BUY executed ({pair}): ${amount:.2f} USDT @ ${order['price']:,.2f}  "
                    f"SL=${params['stop_loss_price']:,.2f}  {tp_log}{ml_log}"
                )
                return
            except Exception as pair_exc:
                log.warning("Skipping %s: %s", pair, pair_exc)
                continue

        log.info("HOLD — no BUY signal on any watched pair.")

    except Exception as exc:
        log.exception("Unhandled error in bot_cycle: %s", exc)
        try:
            err_live = None
            if not config.get("paper_trading", True):
                try:
                    err_live = get_balance_usdt()
                except Exception:
                    pass
            send_alert(
                "ERROR",
                {"error_message": f"{type(exc).__name__}: {exc}"},
                get_portfolio_snapshot(
                    config.get("starting_balance_usdt", 34.00),
                    live_usdt=err_live,
                ),
            )
        except Exception:
            log.error("Also failed to send error email.")


# ── Daily summary (midnight PKT) ──────────────────────────────────────────────

def send_daily_summary() -> None:
    config  = load_config()
    start   = config.get("starting_balance_usdt", 34.00)
    pairs   = get_trading_pairs(config)
    live_usdt = None
    if not config.get("paper_trading", True):
        try:
            live_usdt = get_balance_usdt()
        except Exception as exc:
            log.warning("Daily summary: could not fetch live USDT: %s", exc)
    snap    = get_portfolio_snapshot(start, live_usdt=live_usdt)
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

    tf = config.get("timeframe", "5m")
    strat = config.get("trading_strategy", "day_trading")
    hold_mode = config.get("hold_until_profit", False)
    log.info(
        "Pairs: %s | Timeframe: %s | Paper: %s | Strategy: %s",
        ", ".join(pairs),
        tf,
        paper,
        strat,
    )
    if hold_mode:
        log.info(
            "Hold-until-profit ON: TP=%.1f%%, hard max-loss=%.1f%% "
            "(ignoring normal SL, patterns, RSI-overbought)",
            float(config.get("risk_by_buy_min_conditions", {}).get(
                str(config.get("buy_min_conditions", 2)), {}
            ).get("take_profit_pct", config.get("take_profit_pct", 0.5))),
            float(config.get("max_loss_pct", 3.0)),
        )

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
