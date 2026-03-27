import pandas as pd


# ── Pure-pandas indicator implementations ─────────────────────────────────────
# Identical results to pandas-ta; no external dependency required.

def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=length - 1, min_periods=length).mean()
    avg_loss = loss.ewm(com=length - 1, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _ema(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast    = _ema(close, fast)
    ema_slow    = _ema(close, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


# ── Public API ────────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute RSI(14), MACD(12,26,9), EMA(9), EMA(21) and append as columns.

    Input:  OHLCV DataFrame from data_feed.fetch_ohlcv()
    Output: Same DataFrame with additional columns:
              rsi, macd, macd_signal, macd_hist, ema_fast, ema_slow
    """
    df = df.copy()
    close = df["close"]

    df["rsi"] = _rsi(close, length=14)

    macd_line, signal_line, histogram = _macd(close)
    df["macd"]        = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"]   = histogram

    df["ema_fast"] = _ema(close, length=9)
    df["ema_slow"] = _ema(close, length=21)

    return df


def get_latest_indicators(df: pd.DataFrame) -> dict:
    """
    Return the indicator values from the last row as a plain dict.
    Useful for logging and signal decisions.
    """
    row = df.iloc[-1]

    def _safe(col: str, decimals: int) -> float | None:
        val = row.get(col)
        return round(float(val), decimals) if val is not None and pd.notna(val) else None

    close_val = _safe("close", 2)
    if close_val is None:
        raise ValueError("Last candle close is missing or invalid")

    return {
        "rsi":         _safe("rsi",         2),
        "macd":        _safe("macd",        4),
        "macd_signal": _safe("macd_signal", 4),
        "macd_hist":   _safe("macd_hist",   4),
        "ema_fast":    _safe("ema_fast",    2),
        "ema_slow":    _safe("ema_slow",    2),
        "close":       close_val,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    from modules.data_feed import fetch_ohlcv

    df = fetch_ohlcv(limit=50)
    df = add_indicators(df)
    print(df[["timestamp", "close", "rsi", "macd", "ema_fast", "ema_slow"]].tail(5).to_string())
    print("\nLatest indicators:")
    for k, v in get_latest_indicators(df).items():
        print(f"  {k}: {v}")
