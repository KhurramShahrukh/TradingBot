from modules.trade_logger import get_today_pnl

TRADING_STRATEGY_DAY = "day_trading"
TRADING_STRATEGY_SWING = "swing"


def normalize_trading_strategy(config: dict) -> str:
    """Return ``swing`` only when ``trading_strategy`` is ``swing``; any other value → day_trading."""
    raw = str(config.get("trading_strategy", "")).strip().lower()
    if raw == TRADING_STRATEGY_SWING:
        return TRADING_STRATEGY_SWING
    return TRADING_STRATEGY_DAY


def calculate_stop_loss(buy_price: float, stop_loss_pct: float) -> float:
    """Return the price at which the stop-loss triggers."""
    return round(buy_price * (1 - stop_loss_pct / 100), 2)


def calculate_take_profit(buy_price: float, take_profit_pct: float) -> float:
    """Return the price at which the take-profit triggers."""
    return round(buy_price * (1 + take_profit_pct / 100), 2)


def get_position_size(balance_usdt: float, trade_amount_pct: float, min_order_usdt: float = 10.0) -> float:
    """
    Return the USDT amount to deploy in the next trade.

    Applies 100% of available balance by default (full compounding).
    Returns 0.0 if balance is below the Binance minimum.
    """
    amount = round(balance_usdt * trade_amount_pct / 100, 2)
    if amount < min_order_usdt:
        return 0.0
    return amount


def resolve_risk_pct_from_config(
    config: dict,
    satisfied_legs: int | None = None,
) -> tuple[float, float]:
    """
    Return (stop_loss_pct, take_profit_pct).

    If ``risk_by_buy_min_conditions`` has an entry for ``satisfied_legs``
    (1–3 = how many BUY legs passed on this bar), those values win.
    Otherwise top-level ``stop_loss_pct`` / ``take_profit_pct`` are used.

    ``buy_min_conditions`` only gates whether a BUY fires; it does not select risk.
    """
    if satisfied_legs is not None:
        legs = max(1, min(3, int(satisfied_legs)))
        mapping = config.get("risk_by_buy_min_conditions") or {}
        entry = mapping.get(str(legs))
        if isinstance(entry, dict):
            sl = entry.get("stop_loss_pct")
            tp = entry.get("take_profit_pct")
            if sl is not None and tp is not None:
                return float(sl), float(tp)
    return float(config.get("stop_loss_pct", 0.5)), float(config.get("take_profit_pct", 1.2))


def is_daily_loss_limit_breached(starting_balance: float, config: dict) -> bool:
    """
    Compare today's realised P&L against the daily loss limit.
    Returns True if the bot should stop trading for the rest of the day.
    """
    daily_loss_limit_pct = config.get("daily_loss_limit_pct", 3.0)
    today_pnl = get_today_pnl()   # returns a negative float on a losing day

    if today_pnl >= 0:
        return False

    loss_pct = abs(today_pnl) / starting_balance * 100
    return loss_pct >= daily_loss_limit_pct


def get_risk_parameters(
    buy_price: float,
    balance_usdt: float,
    config: dict,
    satisfied_legs: int | None = None,
) -> dict:
    """
    Return a complete risk parameter dict for a new position.

    ``satisfied_legs`` (1–3) selects ``risk_by_buy_min_conditions`` for this entry;
    omit it to use only top-level stop/take-profit from config.

    For ``trading_strategy`` = ``swing``, only a stop-loss is set;
    ``take_profit_pct`` / ``take_profit_price`` are None (exits on reversal pattern).

    Keys:
        position_size_usdt  — USDT to spend
        stop_loss_price     — price that triggers stop-loss
        take_profit_price   — price that triggers take-profit (None for swing mode)
        stop_loss_pct       — configured stop-loss %
        take_profit_pct     — configured take-profit % (None for swing mode)
    """
    trade_amount_pct = config.get("trade_amount_pct", 100)

    if normalize_trading_strategy(config) == TRADING_STRATEGY_SWING:
        swing_cfg = config.get("swing") or config.get("buy_low_sell_high") or {}
        stop_loss_pct = float(swing_cfg.get("stop_loss_pct", 3.0))
        return {
            "position_size_usdt": get_position_size(balance_usdt, trade_amount_pct),
            "stop_loss_price":    calculate_stop_loss(buy_price, stop_loss_pct),
            "take_profit_price":  None,
            "stop_loss_pct":      stop_loss_pct,
            "take_profit_pct":    None,
        }

    stop_loss_pct, take_profit_pct = resolve_risk_pct_from_config(
        config, satisfied_legs=satisfied_legs
    )

    return {
        "position_size_usdt": get_position_size(balance_usdt, trade_amount_pct),
        "stop_loss_price":    calculate_stop_loss(buy_price, stop_loss_pct),
        "take_profit_price":  calculate_take_profit(buy_price, take_profit_pct),
        "stop_loss_pct":      stop_loss_pct,
        "take_profit_pct":    take_profit_pct,
    }


if __name__ == "__main__":
    import json

    with open("config.json") as f:
        config = json.load(f)

    buy_price = 67_000.00
    balance   = 35.00

    params = get_risk_parameters(buy_price, balance, config)
    print("Risk parameters:")
    for k, v in params.items():
        print(f"  {k}: {v}")

    breached = is_daily_loss_limit_breached(config["starting_balance_usdt"], config)
    print(f"\nDaily loss limit breached: {breached}")
