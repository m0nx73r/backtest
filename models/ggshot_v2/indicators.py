"""Causal indicators for the ggshot_v2 backtest. Every output is aligned to the input index."""

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    pc = df.close.shift()
    return pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR: RMA of the true range."""
    return _true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def supertrend(df: pd.DataFrame, n: int = 14, mult: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Supertrend line and direction (+1 up / -1 down). Same recursion as
    tools/ggshot_research/trigger_probe.supertrend."""
    a = atr(df, n).values
    hl2 = ((df.high + df.low) / 2).values
    up, dn = hl2 - mult * a, hl2 + mult * a
    cl = df.close.values
    fu, fd = up.copy(), dn.copy()
    trend = np.ones(len(df), dtype=int)
    for i in range(1, len(df)):
        fu[i] = max(up[i], fu[i - 1]) if cl[i - 1] > fu[i - 1] else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if cl[i - 1] < fd[i - 1] else dn[i]
        if trend[i - 1] == -1 and cl[i] > fd[i - 1]:
            trend[i] = 1
        elif trend[i - 1] == 1 and cl[i] < fu[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    line = np.where(trend == 1, fu, fd)
    return pd.Series(line, index=df.index), pd.Series(trend, index=df.index)
