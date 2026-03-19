import pandas as pd


# ─── helpers ──────────────────────────────────────────────────────────────────

def _body(row) -> float:
    return abs(row["close"] - row["open"])

def _upper_wick(row) -> float:
    return row["high"] - max(row["close"], row["open"])

def _lower_wick(row) -> float:
    return min(row["close"], row["open"]) - row["low"]

def _is_bullish(row) -> bool:
    return row["close"] > row["open"]

def _is_bearish(row) -> bool:
    return row["close"] < row["open"]


# ─── individual pattern detectors ─────────────────────────────────────────────

def _bullish_engulfing(prev, curr) -> bool:
    """Bearish candle followed by a larger bullish candle that fully covers it."""
    return (
        _is_bearish(prev)
        and _is_bullish(curr)
        and curr["open"] <= prev["close"]
        and curr["close"] >= prev["open"]
        and _body(curr) > _body(prev)
    )

def _bearish_engulfing(prev, curr) -> bool:
    """Bullish candle followed by a larger bearish candle that fully covers it."""
    return (
        _is_bullish(prev)
        and _is_bearish(curr)
        and curr["open"] >= prev["close"]
        and curr["close"] <= prev["open"]
        and _body(curr) > _body(prev)
    )

def _hammer(row) -> bool:
    """
    Small body at the top, long lower wick (≥ 2× body), minimal upper wick.
    Typically bullish when occurring after a downtrend.
    """
    body = _body(row)
    if body == 0:
        return False
    lower = _lower_wick(row)
    upper = _upper_wick(row)
    return lower >= 2 * body and upper <= 0.3 * body

def _shooting_star(row) -> bool:
    """
    Small body at the bottom, long upper wick (≥ 2× body), minimal lower wick.
    Bearish reversal signal after an uptrend.
    """
    body = _body(row)
    if body == 0:
        return False
    upper = _upper_wick(row)
    lower = _lower_wick(row)
    return upper >= 2 * body and lower <= 0.3 * body

def _doji(row) -> bool:
    """Body is very small relative to total range — indecision candle."""
    total_range = row["high"] - row["low"]
    if total_range == 0:
        return False
    return _body(row) / total_range < 0.1

def _morning_star(c1, c2, c3) -> bool:
    """
    3-candle bullish reversal:
      c1 — strong bearish
      c2 — small body (star) with a gap down
      c3 — strong bullish that closes into c1's body
    """
    return (
        _is_bearish(c1) and _body(c1) > 0
        and _body(c2) < 0.3 * _body(c1)
        and _is_bullish(c3)
        and c3["close"] > c1["open"] + (c1["close"] - c1["open"]) * 0.5
    )

def _evening_star(c1, c2, c3) -> bool:
    """
    3-candle bearish reversal:
      c1 — strong bullish
      c2 — small body (star) with a gap up
      c3 — strong bearish that closes into c1's body
    """
    return (
        _is_bullish(c1) and _body(c1) > 0
        and _body(c2) < 0.3 * _body(c1)
        and _is_bearish(c3)
        and c3["close"] < c1["open"] + (c1["close"] - c1["open"]) * 0.5
    )

def _piercing_line(prev, curr) -> bool:
    """
    Bearish candle followed by bullish candle that opens below prev low
    and closes above the midpoint of prev body.
    """
    if not (_is_bearish(prev) and _is_bullish(curr)):
        return False
    midpoint = (prev["open"] + prev["close"]) / 2
    return curr["open"] < prev["low"] and curr["close"] > midpoint


# ─── public API ───────────────────────────────────────────────────────────────

BULLISH_PATTERNS = {"Bullish Engulfing", "Hammer", "Morning Star", "Piercing Line"}
BEARISH_PATTERNS = {"Bearish Engulfing", "Shooting Star", "Evening Star"}


def detect_pattern(df: pd.DataFrame) -> str | None:
    """
    Scan the last 3 rows of the OHLCV DataFrame and return the first
    matching pattern name, or None if nothing is detected.

    Priority: 3-candle patterns checked first, then 2-candle, then 1-candle.
    """
    if len(df) < 3:
        return None

    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    # 3-candle patterns
    if _morning_star(c1, c2, c3):
        return "Morning Star"
    if _evening_star(c1, c2, c3):
        return "Evening Star"

    # 2-candle patterns (prev = c2, curr = c3)
    prev, curr = c2, c3
    if _bullish_engulfing(prev, curr):
        return "Bullish Engulfing"
    if _bearish_engulfing(prev, curr):
        return "Bearish Engulfing"
    if _piercing_line(prev, curr):
        return "Piercing Line"

    # 1-candle patterns on most recent candle
    if _hammer(curr):
        return "Hammer"
    if _shooting_star(curr):
        return "Shooting Star"
    if _doji(curr):
        return "Doji"

    return None


def is_bullish_pattern(pattern: str | None) -> bool:
    return pattern in BULLISH_PATTERNS


def is_bearish_pattern(pattern: str | None) -> bool:
    return pattern in BEARISH_PATTERNS


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "..")
    from modules.data_feed import fetch_ohlcv

    df = fetch_ohlcv(limit=50)
    pattern = detect_pattern(df)
    print(f"Detected pattern: {pattern}")
    print(f"Bullish: {is_bullish_pattern(pattern)}")
    print(f"Bearish: {is_bearish_pattern(pattern)}")
