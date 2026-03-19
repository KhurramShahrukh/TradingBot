import pandas as pd
import pandas_ta as ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute RSI(14), MACD, EMA(fast), EMA(slow) and append them as columns.

    Input:  OHLCV DataFrame from data_feed.fetch_ohlcv()
    Output: Same DataFrame with additional columns:
              rsi, macd, macd_signal, macd_hist, ema_fast, ema_slow
    """
    df = df.copy()

    # RSI
    df["rsi"] = ta.rsi(df["close"], length=14)

    # MACD (default 12, 26, 9)
    macd_df = ta.macd(df["close"])
    if macd_df is not None:
        df["macd"]        = macd_df.iloc[:, 0]   # MACD line
        df["macd_signal"] = macd_df.iloc[:, 2]   # Signal line
        df["macd_hist"]   = macd_df.iloc[:, 1]   # Histogram

    # EMAs
    df["ema_fast"] = ta.ema(df["close"], length=9)
    df["ema_slow"] = ta.ema(df["close"], length=21)

    return df


def get_latest_indicators(df: pd.DataFrame) -> dict:
    """
    Return the indicator values from the last row as a plain dict.
    Useful for logging and signal decisions.
    """
    row = df.iloc[-1]
    return {
        "rsi":        round(float(row["rsi"]),        2) if pd.notna(row.get("rsi"))        else None,
        "macd":       round(float(row["macd"]),       4) if pd.notna(row.get("macd"))       else None,
        "macd_signal":round(float(row["macd_signal"]),4) if pd.notna(row.get("macd_signal"))else None,
        "macd_hist":  round(float(row["macd_hist"]),  4) if pd.notna(row.get("macd_hist"))  else None,
        "ema_fast":   round(float(row["ema_fast"]),   2) if pd.notna(row.get("ema_fast"))   else None,
        "ema_slow":   round(float(row["ema_slow"]),   2) if pd.notna(row.get("ema_slow"))   else None,
        "close":      round(float(row["close"]),      2),
    }


if __name__ == "__main__":
    from data_feed import fetch_ohlcv

    df = fetch_ohlcv(limit=50)
    df = add_indicators(df)
    print(df[["timestamp", "close", "rsi", "macd", "ema_fast", "ema_slow"]].tail(5).to_string())
    print("\nLatest indicators:")
    for k, v in get_latest_indicators(df).items():
        print(f"  {k}: {v}")
