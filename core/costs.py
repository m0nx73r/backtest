"""Execution-cost helpers shared by the backtests.

All functions are pure so they can be unit tested without market data.
"""

import pandas as pd

from core.config import FEE_TAKER, FEE_MAKER, SLIPPAGE_PCT


def bar_duration(df: pd.DataFrame) -> pd.Timedelta:
    """Typical spacing between bars of a DatetimeIndex-ed (or 'timestamp'-column) frame."""
    idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.DatetimeIndex(df["timestamp"])
    if len(idx) < 2:
        raise ValueError("need at least 2 bars to infer bar duration")
    return pd.Series(idx).diff().median()


def to_close_time_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose index is each bar's CLOSE time instead of its OPEN time.

    Exchange candles (ccxt/Binance) are stamped with the bar's open time, but a bar's
    high/low/close are only known once it closes. Re-labelling by close time lets plain
    `index <= now` / `reindex(..., method='ffill')` lookups stay causal.
    """
    out = df.copy()
    out.index = out.index + bar_duration(df)
    return out


def fee_usd(qty: float, price: float, maker: bool) -> float:
    """Exchange fee for one fill of `qty` units at `price`."""
    return abs(qty) * price * (FEE_MAKER if maker else FEE_TAKER)


def round_trip_fees(qty: float, entry: float, exit_price: float,
                    entry_maker: bool, exit_maker: bool) -> float:
    """Total fees for opening and closing `qty` units."""
    return fee_usd(qty, entry, entry_maker) + fee_usd(qty, exit_price, exit_maker)


def slip(price: float, direction: int, is_entry: bool) -> float:
    """Apply adverse slippage to a taker fill. direction: +1 long, -1 short."""
    if not SLIPPAGE_PCT:
        return price
    adverse = direction if is_entry else -direction
    return price * (1 + adverse * SLIPPAGE_PCT)
