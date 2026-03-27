import os
import ccxt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

def get_exchange():
    """Initialise and return an authenticated Binance exchange object."""
    exchange = ccxt.binance({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET_KEY"),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    return exchange


def _as_float(x) -> float | None:
    """Parse a ticker/OHLC field; None or invalid → None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # reject NaN


def _price_from_ticker(ticker: dict) -> float | None:
    """
    Best-effort spot price from a ccxt unified ticker.

    Some pairs (e.g. stablecoins) may omit ``last``; fall back to ``close``,
    mid bid/ask, or bid/ask alone.
    """
    for key in ("last", "close"):
        p = _as_float(ticker.get(key))
        if p is not None and p > 0:
            return p
    bid = _as_float(ticker.get("bid"))
    ask = _as_float(ticker.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2
    if bid is not None and bid > 0:
        return bid
    if ask is not None and ask > 0:
        return ask
    return None


def fetch_ohlcv(pair: str = "BTC/USDT", timeframe: str = "1h", limit: int = 100) -> pd.DataFrame:
    """
    Fetch the last `limit` closed candles for `pair` on `timeframe`.

    Returns a DataFrame with columns:
        timestamp, open, high, low, close, volume
    The last row is the most recent CLOSED candle (current candle is excluded).
    """
    exchange = get_exchange()
    try:
        raw = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit + 1)
    except ccxt.NetworkError as e:
        raise ConnectionError(f"Network error fetching OHLCV: {e}") from e
    except ccxt.ExchangeError as e:
        raise RuntimeError(f"Exchange error fetching OHLCV: {e}") from e

    # Drop the last (still-forming) candle so all rows are closed candles
    raw = raw[:-1]

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    df.reset_index(drop=True, inplace=True)
    return df


def get_current_price(pair: str = "BTC/USDT") -> float:
    """Return the latest ticker price for `pair`."""
    exchange = get_exchange()
    try:
        ticker = exchange.fetch_ticker(pair)
        p = _price_from_ticker(ticker)
        if p is None:
            raise RuntimeError(
                f"No usable price in ticker for {pair} (last/close/bid/ask missing)"
            )
        return p
    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        raise RuntimeError(f"Error fetching ticker: {e}") from e


def get_balance_usdt() -> float:
    """Return available USDT balance in the Spot wallet."""
    exchange = get_exchange()
    try:
        balance = exchange.fetch_balance()
        return float(balance["free"].get("USDT", 0.0))
    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        raise RuntimeError(f"Error fetching balance: {e}") from e


if __name__ == "__main__":
    print("Fetching last 5 candles of BTC/USDT 1h …")
    df = fetch_ohlcv(limit=5)
    print(df.to_string())
    print(f"\nCurrent BTC price: ${get_current_price():,.2f}")
    print(f"USDT balance:      ${get_balance_usdt():.2f}")
