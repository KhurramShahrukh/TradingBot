from modules.trade_logger import get_today_pnl


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


def get_risk_parameters(buy_price: float, balance_usdt: float, config: dict) -> dict:
    """
    Return a complete risk parameter dict for a new position.

    Keys:
        position_size_usdt  — USDT to spend
        stop_loss_price     — price that triggers stop-loss
        take_profit_price   — price that triggers take-profit
        stop_loss_pct       — configured stop-loss %
        take_profit_pct     — configured take-profit %
    """
    stop_loss_pct   = config.get("stop_loss_pct",   0.5)
    take_profit_pct = config.get("take_profit_pct", 1.2)
    trade_amount_pct= config.get("trade_amount_pct",100)

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
