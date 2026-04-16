"""
Binance spot fee helpers via CCXT.

- Schedule: ``fetch_trading_fee`` returns maker/taker (VIP tier, promos). Market
  orders are charged the **taker** rate.
- Actual trade: unified ``order`` dict includes ``fee`` / ``fees`` with currency
  and cost — best source for how much base asset you keep after a BUY.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import ccxt

log = logging.getLogger(__name__)

# Binance default spot tier (no VIP), before promos — used if API unavailable
DEFAULT_MAKER = 0.001
DEFAULT_TAKER = 0.001

_taker_cache: dict[str, float] = {}


def fetch_spot_maker_taker(exchange: "ccxt.binance", pair: str) -> tuple[float, float]:
    """
    Return (maker, taker) fee rates as decimals, e.g. 0.001 = 0.1%.

    Uses CCXT ``fetch_trading_fee`` (Binance SAPI trade fee when authenticated).
    """
    raw: dict[str, Any] = exchange.fetch_trading_fee(pair)
    maker = raw.get("maker")
    taker = raw.get("taker")
    tr = raw.get("trading")
    if isinstance(tr, dict):
        if maker is None:
            maker = tr.get("maker")
        if taker is None:
            taker = tr.get("taker")
    m = float(maker if maker is not None else DEFAULT_MAKER)
    t = float(taker if taker is not None else DEFAULT_TAKER)
    return m, t


def get_cached_taker_fee(pair: str, exchange: "ccxt.binance") -> float:
    """Taker rate for ``pair``, cached per process (rates rarely change)."""
    if pair not in _taker_cache:
        _, t = fetch_spot_maker_taker(exchange, pair)
        _taker_cache[pair] = t
        log.debug("Cached taker fee for %s: %.6f", pair, t)
    return _taker_cache[pair]


def net_base_after_buy_order(order: dict[str, Any], pair: str) -> float:
    """
    Best estimate of **free** base-asset size after a market BUY: ``filled``
    minus any fee charged in the base asset (e.g. BTC).

    If the fee is paid in BNB or USDT, ``filled`` is unchanged here; wallet
    truth remains ``fetch_balance()`` (handled at SELL time).
    """
    filled = float(order.get("filled") or 0)
    if filled <= 0:
        return 0.0
    base = pair.split("/")[0].upper()
    fee_base = 0.0
    for entry in order.get("fees") or []:
        if str(entry.get("currency") or "").upper() == base:
            fee_base += float(entry.get("cost") or 0)
    one = order.get("fee")
    if isinstance(one, dict) and str(one.get("currency") or "").upper() == base:
        fee_base += float(one.get("cost") or 0)
    return max(filled - fee_base, 0.0)


def apply_taker_to_paper_buy(
    quantity: float, price: float, amount_usdt: float, taker: float
) -> float:
    """
    Rough paper BUY: haircut base qty by taker (approximates fee taken from base).

    Not identical to Binance when fees are paid in BNB or quote; good enough for
    paper P&L vs default tier.
    """
    _ = price  # signature parity with callers that pass price
    _ = amount_usdt
    return max(round(quantity * (1.0 - taker), 8), 0.0)


def apply_taker_to_paper_sell(proceeds: float, taker: float) -> float:
    """Rough paper SELL: haircut quote proceeds by taker."""
    return max(round(proceeds * (1.0 - taker), 2), 0.0)
