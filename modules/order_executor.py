import os
import ccxt
from dotenv import load_dotenv

from modules.exchange_fees import (
    DEFAULT_TAKER,
    apply_taker_to_paper_buy,
    apply_taker_to_paper_sell,
    get_cached_taker_fee,
    net_base_after_buy_order,
)

load_dotenv()


def _free_usdt(balance: dict) -> float:
    """CCXT may expose USDT under ``balance['USDT']['free']`` or ``balance['free']['USDT']``."""
    u = balance.get("USDT")
    if isinstance(u, dict) and u.get("free") is not None:
        return float(u["free"])
    free = balance.get("free")
    if isinstance(free, dict) and free.get("USDT") is not None:
        return float(free["USDT"])
    return 0.0


def _get_exchange() -> ccxt.binance:
    return ccxt.binance({
        "apiKey":          os.getenv("BINANCE_API_KEY"),
        "secret":          os.getenv("BINANCE_SECRET_KEY"),
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
            "fetchCurrencies": False,
        },
    })


def _taker_fee_for_pair(pair: str) -> float:
    """Spot taker rate from Binance (cached); falls back if API keys / call fail."""
    try:
        return get_cached_taker_fee(pair, _get_exchange())
    except Exception:
        return DEFAULT_TAKER


# ── Paper-trading simulator ────────────────────────────────────────────────────

def _paper_buy(pair: str, amount_usdt: float, price: float) -> dict:
    """Simulate a BUY market order without touching the exchange."""
    gross = round(amount_usdt / price, 8)
    taker = _taker_fee_for_pair(pair)
    quantity = apply_taker_to_paper_buy(gross, price, amount_usdt, taker)
    print(
        f"[PAPER] BUY  {quantity} {pair.split('/')[0]} @ ${price:,.2f}  "
        f"(${amount_usdt:.2f} USDT, taker~{taker * 100:.3f}%)"
    )
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
    gross = round(quantity * price, 2)
    taker = _taker_fee_for_pair(pair)
    proceeds = apply_taker_to_paper_sell(gross, taker)
    print(
        f"[PAPER] SELL {quantity} {pair.split('/')[0]} @ ${price:,.2f}  "
        f"(${proceeds:.2f} USDT, taker~{taker * 100:.3f}%)"
    )
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
    """
    Place a real market BUY on Binance for ``amount_usdt`` quote (USDT) spent.

    Uses ``create_market_buy_order_with_cost`` so CCXT always sends
    ``quoteOrderQty`` / ``cost``. A plain ``create_market_buy_order(symbol,
    amount)`` treats ``amount`` as **base** size when the quote path is not
    applied — e.g. ``amount=35`` can mean **35 TAO**, not **$35 USDT**, which
    triggers insufficient balance with a small USDT wallet.
    """
    exchange = _get_exchange()
    try:
        balance = exchange.fetch_balance()
        free_usdt = _free_usdt(balance)
        if free_usdt <= 0:
            raise RuntimeError(f"No free USDT for BUY (free={free_usdt})")
        # Cap to wallet; 100% + rounding can otherwise exceed free slightly.
        spend = min(float(amount_usdt), free_usdt)
        spend = float(exchange.cost_to_precision(pair, spend))
        if spend > free_usdt:
            spend = float(exchange.cost_to_precision(pair, free_usdt * 0.999))
        if spend < 10:
            raise RuntimeError(
                f"USDT spend below minimum after balance/precision "
                f"(spend={spend}, free={free_usdt}, requested={amount_usdt})"
            )
        order = exchange.create_market_buy_order_with_cost(pair, spend)
        filled_price = float(order.get("average") or order.get("price") or 0)
        filled_qty = float(order.get("filled") or 0)
        net_base = net_base_after_buy_order(order, pair)
        # Prefer net base after base-asset fees; else raw fill (fee in BNB/USDT).
        qty_out = net_base if net_base > 0 else filled_qty
        print(f"[LIVE] BUY  {filled_qty} {pair.split('/')[0]} @ ${filled_price:,.2f}  (tracked qty={qty_out})")
        return {
            "order_id": str(order["id"]),
            "type":     "BUY",
            "pair":     pair,
            "price":    filled_price,
            "amount":   spend,
            "quantity": qty_out,
            "status":   order.get("status", "unknown"),
            "paper":    False,
        }
    except (ccxt.NetworkError, ccxt.ExchangeError) as e:
        raise RuntimeError(f"Live BUY failed: {e}") from e


def _live_sell(pair: str, quantity: float) -> dict:
    """Place a real market SELL order on Binance for `quantity` base asset."""
    exchange = _get_exchange()
    base = pair.split("/")[0]
    try:
        # Buy `filled` can exceed *free* base balance: Binance often deducts the
        # trading fee from the acquired asset, so we must not sell more than free.
        balance = exchange.fetch_balance()
        free = float((balance.get(base) or {}).get("free") or 0)
        if free <= 0:
            raise RuntimeError(f"No free {base} to sell (free={free})")
        qty = min(quantity, free)
        qty = float(exchange.amount_to_precision(pair, qty))
        if qty <= 0:
            raise RuntimeError(
                f"Sell amount after precision is zero (requested={quantity}, free={free})"
            )
        order = exchange.create_market_sell_order(symbol=pair, amount=qty)
        filled_qty = float(order.get("filled") or qty)
        filled_price = float(order.get("average") or order.get("price") or 0)
        proceeds = round(filled_price * filled_qty, 2)
        print(f"[LIVE] SELL {filled_qty} {base} @ ${filled_price:,.2f}")
        return {
            "order_id": str(order["id"]),
            "type":     "SELL",
            "pair":     pair,
            "price":    filled_price,
            "amount":   proceeds,
            "quantity": filled_qty,
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
