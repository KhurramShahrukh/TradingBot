import pandas as pd
from modules.indicators import add_indicators, get_latest_indicators
from modules.patterns import detect_pattern, is_bullish_pattern, is_bearish_pattern
from modules.risk_manager import (
    TRADING_STRATEGY_SWING,
    normalize_trading_strategy,
    resolve_risk_pct_from_config,
)


def generate_signal(
    df: pd.DataFrame,
    config: dict,
    position_open: bool = False,
    buy_price: float | None = None,
    current_price: float | None = None,
    entry_stop_loss_pct: float | None = None,
    entry_take_profit_pct: float | None = None,
) -> dict:
    """
    Analyse indicators + candlestick patterns and return a signal dict.

    BUY (config-driven):
        Three legs: bullish pattern, RSI < rsi_oversold, close > EMA slow.

        * ``trading_strategy`` ``day_trading``: ``buy_min_conditions`` (1–3) gates
          how many legs must pass; risk tiers use ``buy_legs`` on BUY signals.

        * ``trading_strategy`` ``swing``: **all three** legs must pass.

    SELL when ``swing`` and a position is open:
        Stop-loss only (no fixed take-profit); exit on bearish reversal pattern.
        RSI-overbought exits are **not** used (ride the move). Day-trading mode
        keeps take-profit, bearish pattern, and RSI-overbought exits.

    Signal dict keys:
        signal        — "BUY" | "SELL" | "HOLD"
        reason        — human-readable explanation
        buy_legs      — on BUY only: how many legs passed (1–3)
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
    strategy = normalize_trading_strategy(config)

    if position_open and buy_price is not None:
        if entry_stop_loss_pct is not None:
            stop_loss_pct = entry_stop_loss_pct
        else:
            stop_loss_pct, _ = resolve_risk_pct_from_config(config)
        take_profit_pct = entry_take_profit_pct
    else:
        stop_loss_pct, take_profit_pct = resolve_risk_pct_from_config(config)

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
        stop_price = buy_price * (1 - stop_loss_pct / 100)

        if price <= stop_price:
            result.update(signal="SELL", reason=f"Stop-loss hit @ ${price:,.2f} (limit ${stop_price:,.2f})")
            return result

        if take_profit_pct is not None:
            target_price = buy_price * (1 + take_profit_pct / 100)
            if price >= target_price:
                result.update(
                    signal="SELL",
                    reason=f"Take-profit hit @ ${price:,.2f} (target ${target_price:,.2f})",
                )
                return result

        if is_bearish_pattern(pattern):
            result.update(signal="SELL", reason=f"Bearish pattern: {pattern}")
            return result

        if strategy != TRADING_STRATEGY_SWING and rsi is not None and rsi > rsi_overbought:
            result.update(signal="SELL", reason=f"RSI overbought: {rsi:.1f} > {rsi_overbought}")
            return result

    # ── BUY checks (only when no position is open) ────────────────────────────
    if not position_open:
        above_ema_slow = ema_slow is not None and close > ema_slow

        bullish_pat_present = is_bullish_pattern(pattern)
        rsi_ok              = rsi is not None and rsi < rsi_oversold
        trend_ok            = above_ema_slow

        if strategy == TRADING_STRATEGY_SWING:
            min_req = 3
        else:
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
                buy_legs=satisfied,
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
