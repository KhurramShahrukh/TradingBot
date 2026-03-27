"""
test_run.py — Pre-flight smoke test for the Trading Bot.

Run this BEFORE starting main.py to confirm:
  1. Binance API connects and returns live price data
  2. Indicators compute without errors
  3. Signal engine produces a valid signal
  4. SQLite database initialises
  5. Email alert is sent (check your inbox!)

Usage:
    python test_run.py
"""

import sys
import json
import traceback
from pathlib import Path

# Ensure project root is on the path when running directly
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

PASS = "  [OK]"
FAIL = "  [FAIL]"


# ── Individual checks ─────────────────────────────────────────────────────────

def check_env() -> bool:
    import os
    required = [
        "BINANCE_API_KEY",
        "BINANCE_SECRET_KEY",
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "EMAIL_SENDER",
        "EMAIL_RECEIVER",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"{FAIL} .env is missing: {', '.join(missing)}")
        return False
    print(f"{PASS} .env — all 7 credentials loaded")
    return True


def check_config() -> dict | None:
    try:
        with open("config.json") as f:
            cfg = json.load(f)
        paper = cfg.get("paper_trading", True)
        plist = cfg.get("trading_pairs")
        if isinstance(plist, list) and plist:
            pair_line = ", ".join(plist)
        else:
            pair_line = cfg.get("trading_pair", "BTC/USDT")
        strat = cfg.get("trading_strategy", "day_trading")
        print(
            f"{PASS} config.json — paper_trading={paper}, pairs={pair_line}, "
            f"tf={cfg['timeframe']}, strategy={strat}"
        )
        if not paper:
            print("       WARNING: paper_trading is FALSE — bot will place REAL orders!")
        return cfg
    except Exception as e:
        print(f"{FAIL} config.json — {e}")
        return None


def check_data_feed(config: dict) -> tuple:
    try:
        from modules.data_feed import fetch_ohlcv, get_current_price
        plist = config.get("trading_pairs")
        pair = plist[0] if isinstance(plist, list) and plist else config.get("trading_pair", "BTC/USDT")
        tf = config.get("timeframe", "15m")
        df = fetch_ohlcv(pair, tf, limit=100)
        price = get_current_price(pair)
        base = pair.split("/")[0]
        print(f"{PASS} data_feed — fetched {len(df)} candles, {base} price ${price:,.2f}")
        return df, price
    except Exception as e:
        print(f"{FAIL} data_feed — {e}")
        traceback.print_exc()
        return None, None


def check_indicators(df) -> None:
    try:
        from modules.indicators import add_indicators, get_latest_indicators
        df = add_indicators(df)
        ind = get_latest_indicators(df)
        print(
            f"{PASS} indicators — RSI={ind['rsi']}, "
            f"EMA9={ind['ema_fast']}, EMA21={ind['ema_slow']}, "
            f"MACD={ind['macd']}"
        )
    except Exception as e:
        print(f"{FAIL} indicators — {e}")
        traceback.print_exc()


def check_patterns(df) -> None:
    try:
        from modules.patterns import detect_pattern, is_bullish_pattern, is_bearish_pattern
        pattern = detect_pattern(df)
        bull = is_bullish_pattern(pattern)
        bear = is_bearish_pattern(pattern)
        print(f"{PASS} patterns — detected: {pattern!r}  (bullish={bull}, bearish={bear})")
    except Exception as e:
        print(f"{FAIL} patterns — {e}")
        traceback.print_exc()


def check_signal(df, price, config) -> None:
    try:
        from modules.signal_engine import generate_signal
        sig = generate_signal(df, config, position_open=False, current_price=price)
        print(
            f"{PASS} signal_engine — signal={sig['signal']!r}, "
            f"RSI={sig['rsi']}, pattern={sig['pattern']!r}"
        )
        print(f"         reason: {sig['reason']}")
    except Exception as e:
        print(f"{FAIL} signal_engine — {e}")
        traceback.print_exc()


def check_risk_manager(price, config) -> None:
    try:
        from modules.risk_manager import get_risk_parameters, is_daily_loss_limit_breached
        start = config.get("starting_balance_usdt", 34.0)
        params = get_risk_parameters(price, start, config)
        tp = params.get("take_profit_price")
        tp_part = f"TP=${tp:,.2f}" if tp is not None else "TP=— (swing / no fixed target)"
        print(
            f"{PASS} risk_manager — size=${params['position_size_usdt']:.2f}, "
            f"SL=${params['stop_loss_price']:,.2f}, {tp_part}"
        )
    except Exception as e:
        print(f"{FAIL} risk_manager — {e}")
        traceback.print_exc()


def check_database() -> None:
    try:
        from modules.trade_logger import init_db, get_today_pnl, get_all_trades
        init_db()
        pnl = get_today_pnl()
        count = len(get_all_trades())
        print(f"{PASS} trade_logger — DB ready, today P&L=${pnl:.2f}, total trades logged={count}")
    except Exception as e:
        print(f"{FAIL} trade_logger — {e}")
        traceback.print_exc()


def check_email(config) -> None:
    try:
        from modules.email_alerts import send_alert
        start = config.get("starting_balance_usdt", 34.0)
        portfolio = {"starting": start, "current": start, "pnl_today": 0.0, "total_pnl": 0.0}
        ok = send_alert(
            "ERROR",
            {"error_message": "Pre-flight test — Trading Bot is online and ready."},
            portfolio,
        )
        if ok:
            print(f"{PASS} email_alerts — test email sent! Check your inbox.")
        else:
            print(f"{FAIL} email_alerts — send failed (check GMAIL_* credentials in .env)")
    except Exception as e:
        print(f"{FAIL} email_alerts — {e}")
        traceback.print_exc()


def check_paper_executor(price, config) -> None:
    try:
        from modules.order_executor import execute_buy, execute_sell
        start = config.get("starting_balance_usdt", 34.0)
        buy  = execute_buy("BTC/USDT", start, price, paper=True)
        sell = execute_sell("BTC/USDT", buy["quantity"], price * 1.01, paper=True)
        pnl  = sell["amount"] - buy["amount"]
        print(f"{PASS} order_executor — paper BUY then SELL simulated, P&L=${pnl:+.4f}")
    except Exception as e:
        print(f"{FAIL} order_executor — {e}")
        traceback.print_exc()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 55)
    print("  Trading Bot — Pre-flight Smoke Test")
    print("=" * 55)

    # 1. Environment & config
    print("\n[1/9] Environment variables")
    if not check_env():
        print("\nFix .env before continuing.")
        sys.exit(1)

    print("\n[2/9] config.json")
    config = check_config()
    if config is None:
        sys.exit(1)

    # 2. Market data
    print("\n[3/9] Binance data feed")
    df, price = check_data_feed(config)
    if df is None:
        print("\nCannot continue without market data.")
        sys.exit(1)

    # 3. Analytics pipeline
    print("\n[4/9] Technical indicators")
    check_indicators(df)

    print("\n[5/9] Candlestick patterns")
    check_patterns(df)

    print("\n[6/9] Signal engine")
    check_signal(df, price, config)

    print("\n[7/9] Risk manager")
    check_risk_manager(price, config)

    # 4. Infrastructure
    print("\n[8/9] Database (SQLite)")
    check_database()

    print("\n[9/9] Paper order executor")
    check_paper_executor(price, config)

    # 5. Email last (so user must wait for inbox confirm)
    print("\n[BONUS] Email alert")
    check_email(config)

    print("\n" + "=" * 55)
    print("  Pre-flight complete.")
    print("  If all checks show [OK], run:  python main.py")
    print("=" * 55)


if __name__ == "__main__":
    main()
