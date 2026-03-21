import pandas as pd
from modules.indicators import add_indicators, get_latest_indicators
from modules.patterns import detect_pattern, is_bullish_pattern, is_bearish_pattern


def generate_signal(
    df: pd.DataFrame,
    config: dict,
    position_open: bool = False,
    buy_price: float | None = None,
    current_price: float | None = None,
) -> dict:
    """
    Analyse indicators + candlestick patterns and return a signal dict.

    BUY (config-driven):
        Three legs: bullish pattern, RSI < rsi_oversold, close > EMA21.
        buy_min_conditions: 2 → any two legs; 3 → all three (strict / default).

    Signal dict keys:
        signal        — "BUY" | "SELL" | "HOLD"
        reason        — human-readable explanation
        pattern       — detected candlestick pattern name or None
        rsi           — current RSI value
        ema_fast      — current EMA fast value
        ema_slow      — current EMA slow value
        close         — latest close price
    """
    df = add_indicators(df)
    ind = get_latest_indicators(df)
    pattern = detect_pattern(df)

    rsi       = ind["rsi"]
    ema_fast  = ind["ema_fast"]
    ema_slow  = ind["ema_slow"]
    close     = ind["close"]
    price     = current_price if current_price is not None else close

    rsi_oversold   = config.get("rsi_oversold",  35)
    rsi_overbought = config.get("rsi_overbought", 65)
    stop_loss_pct  = config.get("stop_loss_pct",  0.5)
    take_profit_pct= config.get("take_profit_pct",1.2)

    result = {
        "signal":   "HOLD",
        "reason":   "No signal conditions met",
        "pattern":  pattern,
        "rsi":      rsi,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "close":    close,
    }

    # ── SELL checks (highest priority when a position is open) ────────────────
    if position_open and buy_price is not None:
        stop_price   = buy_price * (1 - stop_loss_pct   / 100)
        target_price = buy_price * (1 + take_profit_pct / 100)

        if price <= stop_price:
            result.update(signal="SELL", reason=f"Stop-loss hit @ ${price:,.2f} (limit ${stop_price:,.2f})")
            return result

        if price >= target_price:
            result.update(signal="SELL", reason=f"Take-profit hit @ ${price:,.2f} (target ${target_price:,.2f})")
            return result

        if is_bearish_pattern(pattern):
            result.update(signal="SELL", reason=f"Bearish pattern: {pattern}")
            return result

        if rsi is not None and rsi > rsi_overbought:
            result.update(signal="SELL", reason=f"RSI overbought: {rsi:.1f} > {rsi_overbought}")
            return result

    # ── BUY checks (only when no position is open) ────────────────────────────
    if not position_open:
        above_ema_slow = ema_slow is not None and close > ema_slow

        bullish_pat_present = is_bullish_pattern(pattern)
        rsi_ok              = rsi is not None and rsi < rsi_oversold
        trend_ok            = above_ema_slow

        # How many of the three legs must be true (2 = more trades, 3 = strict/original)
        min_req = int(config.get("buy_min_conditions", 3))
        min_req = max(1, min(3, min_req))

        satisfied = int(bullish_pat_present) + int(rsi_ok) + int(trend_ok)

        if satisfied >= min_req:
            parts: list[str] = []
            if bullish_pat_present and pattern:
                parts.append(pattern)
            elif bullish_pat_present:
                parts.append("bullish pattern")
            if rsi_ok and rsi is not None:
                parts.append(f"RSI {rsi:.1f}")
            if trend_ok:
                parts.append("above EMA21")

            result.update(
                signal="BUY",
                reason=" + ".join(parts) if parts else f"{satisfied}/{min_req} conditions",
            )
            return result

    return result


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, "..")
    from modules.data_feed import fetch_ohlcv, get_current_price

    with open("config.json") as f:
        config = json.load(f)

    df = fetch_ohlcv(limit=100)
    price = get_current_price()
    sig = generate_signal(df, config, position_open=False, current_price=price)

    print(f"Signal:  {sig['signal']}")
    print(f"Reason:  {sig['reason']}")
    print(f"Pattern: {sig['pattern']}")
    print(f"RSI:     {sig['rsi']}")
    print(f"EMA9:    {sig['ema_fast']}")
    print(f"EMA21:   {sig['ema_slow']}")
    print(f"Close:   ${sig['close']:,.2f}")
