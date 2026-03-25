import json
import os
from datetime import datetime

import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

PKT = pytz.timezone("Asia/Karachi")

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

ALERT_TYPES = {"BUY", "SELL - PROFIT", "SELL - STOP LOSS", "DAILY SUMMARY", "ERROR"}


def _now_pkt() -> str:
    return datetime.now(PKT).strftime("%Y-%m-%d %H:%M PKT")


def _build_subject(alert_type: str, trade_data: dict) -> str:
    pair  = trade_data.get("pair",  "BTC/USDT")
    price = trade_data.get("price", 0.0)

    if alert_type == "BUY":
        return f"[BUY] {pair} executed @ ${price:,.2f}"
    if alert_type == "SELL - PROFIT":
        return f"[SELL - PROFIT] {pair} closed @ ${price:,.2f}"
    if alert_type == "SELL - STOP LOSS":
        return f"[SELL - STOP LOSS] {pair} stop triggered @ ${price:,.2f}"
    if alert_type == "DAILY SUMMARY":
        return f"[DAILY SUMMARY] {pair} · {trade_data.get('date', _now_pkt()[:10])}"
    if alert_type == "ERROR":
        return f"[ERROR] Trading Bot · {_now_pkt()}"
    return f"[{alert_type}] Trading Bot"


def _build_body(alert_type: str, trade_data: dict, portfolio_data: dict) -> str:
    """Compose the plain-text email body."""

    sep = "─" * 25

    if alert_type == "ERROR":
        return (
            f"ERROR ALERT\n{sep}\n"
            f"{trade_data.get('error_message', 'Unknown error')}\n\n"
            f"Sent by Trading Bot · {_now_pkt()}"
        )

    if alert_type == "DAILY SUMMARY":
        start   = portfolio_data.get("starting",    0.0)
        current = portfolio_data.get("current",     0.0)
        pnl_day = portfolio_data.get("pnl_today",   0.0)
        pnl_tot = portfolio_data.get("total_pnl",   0.0)
        pnl_day_pct = (pnl_day / start * 100) if start else 0.0
        pnl_tot_pct = (pnl_tot / start * 100) if start else 0.0
        trades  = portfolio_data.get("trades_today", 0)

        return (
            f"DAILY SUMMARY\n{sep}\n"
            f"Date:          {trade_data.get('date', _now_pkt()[:10])}\n"
            f"Trades today:  {trades}\n\n"
            f"Portfolio\n{sep}\n"
            f"Starting:      ${start:.2f}\n"
            f"Current:       ${current:.2f}\n"
            f"P&L today:     ${pnl_day:+.2f} ({pnl_day_pct:+.2f}%)\n"
            f"Total P&L:     ${pnl_tot:+.2f} ({pnl_tot_pct:+.2f}%)\n\n"
            f"Sent by Trading Bot · {_now_pkt()}"
        )

    # ── Trade alerts (BUY / SELL variants) ────────────────────────────────────
    t_type    = trade_data.get("type",        alert_type)
    pair      = trade_data.get("pair",        "BTC/USDT")
    price     = trade_data.get("price",       0.0)
    amount    = trade_data.get("amount",      0.0)
    signal    = trade_data.get("signal",      "—")
    sl_price  = trade_data.get("stop_loss",   None)
    tp_price  = trade_data.get("take_profit", None)

    start     = portfolio_data.get("starting",  0.0)
    current   = portfolio_data.get("current",   0.0)
    pnl_day   = portfolio_data.get("pnl_today", 0.0)
    pnl_tot   = portfolio_data.get("total_pnl", 0.0)
    pnl_day_pct = (pnl_day / start * 100) if start else 0.0
    pnl_tot_pct = (pnl_tot / start * 100) if start else 0.0

    sl_line = f"Stop-loss:     ${sl_price:,.2f} (-{trade_data.get('stop_loss_pct', 0.5):.1f}%)" if sl_price else ""
    tp_line = f"Take-profit:   ${tp_price:,.2f} (+{trade_data.get('take_profit_pct', 1.2):.1f}%)" if tp_price else ""

    trade_section = (
        f"Trade Summary\n{sep}\n"
        f"Type:          {t_type}\n"
        f"Pair:          {pair}\n"
        f"Price:         ${price:,.2f}\n"
        f"Amount:        ${amount:.2f} USDT\n"
        f"Signal:        {signal}\n"
    )
    if sl_line:
        trade_section += f"{sl_line}\n"
    if tp_line:
        trade_section += f"{tp_line}\n"

    portfolio_section = (
        f"\nPortfolio\n{sep}\n"
        f"Starting:      ${start:.2f}\n"
        f"Current:       ${current:.2f}\n"
        f"P&L today:     ${pnl_day:+.2f} ({pnl_day_pct:+.2f}%)\n"
        f"Total P&L:     ${pnl_tot:+.2f} ({pnl_tot_pct:+.2f}%)\n"
    )

    return trade_section + portfolio_section + f"\nSent by Trading Bot · {_now_pkt()}"


def send_alert(alert_type: str, trade_data: dict, portfolio_data: dict) -> bool:
    """
    Send a formatted email alert via SendGrid HTTP API.

    Parameters
    ----------
    alert_type     : one of ALERT_TYPES
    trade_data     : dict with keys like pair, price, amount, signal, etc.
    portfolio_data : dict with keys starting, current, pnl_today, total_pnl

    Returns True on success, False on failure (does NOT re-raise).
    """
    api_key  = os.getenv("SENDGRID_API_KEY")
    sender   = os.getenv("EMAIL_SENDER")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not all([api_key, sender, receiver]):
        print("[email_alerts] Missing SENDGRID_API_KEY / EMAIL_SENDER / EMAIL_RECEIVER in .env — alert not sent.")
        return False

    subject = _build_subject(alert_type, trade_data)
    body    = _build_body(alert_type, trade_data, portfolio_data)

    payload = {
        "personalizations": [{"to": [{"email": receiver}]}],
        "from": {"email": sender},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    try:
        response = requests.post(
            SENDGRID_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=10,
        )
        if response.status_code in (200, 202):
            print(f"[email_alerts] Sent: {subject}")
            return True
        print(f"[email_alerts] SendGrid error {response.status_code}: {response.text}")
        return False
    except Exception as e:
        print(f"[email_alerts] Failed to send email: {e}")
        return False


if __name__ == "__main__":
    trade = {
        "type":           "BUY",
        "pair":           "BTC/USDT",
        "price":          67_842.00,
        "amount":         35.00,
        "signal":         "Bullish Engulfing + RSI 34",
        "stop_loss":      67_503.00,
        "take_profit":    68_218.00,
        "stop_loss_pct":  0.5,
        "take_profit_pct":1.2,
    }
    portfolio = {
        "starting":  35.00,
        "current":   35.00,
        "pnl_today":  0.00,
        "total_pnl":  0.00,
    }
    ok = send_alert("BUY", trade, portfolio)
    print(f"Alert sent: {ok}")
