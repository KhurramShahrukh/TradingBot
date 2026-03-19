import os
import ccxt
from dotenv import load_dotenv

load_dotenv()


def _get_exchange() -> ccxt.binance:
    return ccxt.binance({
        "apiKey":          os.getenv("BINANCE_API_KEY"),
        "secret":          os.getenv("BINANCE_SECRET_KEY"),
        "enableRateLimit": True,
        "options":         {"defaultType": "spot"},
    })


# ── Paper-trading simulator ────────────────────────────────────────────────────

def _paper_buy(pair: str, amount_usdt: float, price: float) -> dict:
    """Simulate a BUY market order without touching the exchange."""
    quantity = round(amount_usdt / price, 6)
    print(f"[PAPER] BUY  {quantity} {pair.split('/')[0]} @ ${price:,.2f}  (${amount_usdt:.2f} USDT)")
    return {
        "order_id":  "PAPER-BUY",
        "type":      "BUY",
        "pair":      pair,
        "price":     price,
        "amount":    amount_usdt,
        "quantity":  quantity,
        "status":    "filled",
        "paper":     True,
    }


def _paper_sell(pair: str, quantity: float, price: float) -> dict:
    """Simulate a SELL market order without touching the exchange."""
    proceeds = round(quantity * price, 2)
    print(f"[PAPER] SELL {quantity} {pair.split('/')[0]} @ ${price:,.2f}  (${proceeds:.2f} USDT)")
    return {
        "order_id":  "PAPER-SELL",
        "type":      "SELL",
        "pair":      pair,
        "price":     price,
        "amount":    proceeds,
        "quantity":  quantity,
        "status":    "filled",
        "paper":     True,
    }


# ── Live order placement ───────────────────────────────────────────────────────

def _live_buy(pair: str, amount_usdt: float) -> dict:
    """Place a real market BUY order on Binance (cost = amount_usdt)."""
    exchange = _get_exchange()
    try:
        order = exchange.create_market_buy_order(
            symbol=pair,
            amount=amount_usdt,
            params={"quoteOrderQty": amount_usdt},
        )
        filled_price = float(order.get("average") or order.get("price") or 0)
        filled_qty   = float(order.get("filled") or 0)
        print(f"[LIVE] BUY  {filled_qty} {pair.split('/')[0]} @ ${filled_price:,.2f}")
        return {
            "order_id": str(order["id"]),
            "type":     "BUY",
            "pair":     pair,
            "price":    filled_price,
            "amount":   amount_usdt,
            "quantity": filled_qty,
            "status":   order.get("status", "unknown"),
            "paper":    False,
        }
    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        raise RuntimeError(f"Live BUY failed: {e}") from e


def _live_sell(pair: str, quantity: float) -> dict:
    """Place a real market SELL order on Binance for `quantity` base asset."""
    exchange = _get_exchange()
    try:
        order = exchange.create_market_sell_order(symbol=pair, amount=quantity)
        filled_price = float(order.get("average") or order.get("price") or 0)
        proceeds     = round(filled_price * quantity, 2)
        print(f"[LIVE] SELL {quantity} {pair.split('/')[0]} @ ${filled_price:,.2f}")
        return {
            "order_id": str(order["id"]),
            "type":     "SELL",
            "pair":     pair,
            "price":    filled_price,
            "amount":   proceeds,
            "quantity": quantity,
            "status":   order.get("status", "unknown"),
            "paper":    False,
        }
    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        raise RuntimeError(f"Live SELL failed: {e}") from e


# ── Public API ─────────────────────────────────────────────────────────────────

def execute_buy(pair: str, amount_usdt: float, price: float, paper: bool = True) -> dict:
    """
    Execute a BUY.

    Parameters
    ----------
    pair         : e.g. "BTC/USDT"
    amount_usdt  : USDT to spend
    price        : current market price (used for paper mode sizing)
    paper        : True → simulate; False → real order
    """
    if paper:
        return _paper_buy(pair, amount_usdt, price)
    return _live_buy(pair, amount_usdt)


def execute_sell(pair: str, quantity: float, price: float, paper: bool = True) -> dict:
    """
    Execute a SELL.

    Parameters
    ----------
    pair      : e.g. "BTC/USDT"
    quantity  : base-asset quantity to sell (BTC)
    price     : current market price (used for paper mode proceeds)
    paper     : True → simulate; False → real order
    """
    if paper:
        return _paper_sell(pair, quantity, price)
    return _live_sell(pair, quantity)


if __name__ == "__main__":
    print("=== Paper trading test ===")
    buy  = execute_buy("BTC/USDT",  35.00, 67_000.00, paper=True)
    sell = execute_sell("BTC/USDT", buy["quantity"], 67_804.00, paper=True)
    pnl  = sell["amount"] - buy["amount"]
    print(f"P&L: ${pnl:+.4f}")
