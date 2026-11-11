"""Momentum-breakout detector: a loose superset scan, then a parameter filter.

`scan` evaluates every bar once with the loosest rule; `apply_params` narrows the result for a
given parameter set, so parameter sweeps never re-scan the bars. Everything is causal: a row's
values depend only on bars up to and including its own, and `decision_time` is the bar close.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind

SCAN_LOOKBACKS = (15, 20, 25, 30)
SCAN_RSI_MIN = 55.0
SCAN_VOL_MIN = 1.0
WARMUP_BARS = 100
VOL_WINDOW = 20
RUN_BARS = 10
SWING_BARS = 10
ATR_PCT_WINDOW = 500
HTF_DURATION = pd.Timedelta(hours=4)

COLUMNS = ["signal_time", "decision_time", "side", "close", "atr", "rsi", "vol_ratio",
           *[f"ext{n}" for n in SCAN_LOOKBACKS], "run10_atr", "atr_pct", "htf_ok", "hour",
           "swing_low", "swing_high", "st_line"]


@dataclass(frozen=True)
class DetectorParams:
    lookback: int = 20
    rsi_level: float = 60.0
    vol_mult: float = 1.0
    htf_trend: bool = False
    max_run_atr: float | None = None
    hours: tuple[int, ...] | None = None
    atr_pct_range: tuple[float, float] | None = None


def _rolling_rank(x: np.ndarray, window: int) -> np.ndarray:
    """Percentile rank (0-1) of each value within the trailing `window` values incl. itself."""
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        w = x[max(0, i - window + 1):i + 1]
        w = w[~np.isnan(w)]
        out[i] = (w <= x[i]).sum() / len(w)
    return out


def _htf_trend(decision_time: pd.Series, bars_4h: pd.DataFrame | None) -> np.ndarray:
    """+1 / -1 / 0 trend of the latest 4h bar closed by each decision time (0 = unknown/flat)."""
    if bars_4h is None or len(bars_4h) == 0:
        return np.zeros(len(decision_time), dtype=int)
    diff = ind.ema(bars_4h.close, 20) - ind.ema(bars_4h.close, 50)
    trend = np.sign(diff.values).astype(int)
    closed_at = (bars_4h.index + HTF_DURATION).tz_convert("UTC").tz_localize(None).to_numpy()
    pos = np.searchsorted(closed_at, decision_time.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(), side="right") - 1
    return np.where(pos >= 0, trend[np.clip(pos, 0, None)], 0)


def scan(bars: pd.DataFrame, bars_4h: pd.DataFrame | None) -> pd.DataFrame:
    """One row per bar passing the loosest breakout rule on either side (see module docstring)."""
    if len(bars) <= WARMUP_BARS:
        return pd.DataFrame(columns=COLUMNS)
    dur = pd.Series(bars.index).diff().median()
    close = bars.close
    atr = ind.atr(bars, 14)
    rsi = ind.rsi(close, 14)
    trend = np.sign((ind.ema(close, 20) - ind.ema(close, 50)).values).astype(int)
    vol_ratio = bars.volume / bars.volume.shift(1).rolling(VOL_WINDOW).mean()
    hi_n = {n: close.rolling(n).max() for n in SCAN_LOOKBACKS}
    lo_n = {n: close.rolling(n).min() for n in SCAN_LOOKBACKS}
    st_line, _ = ind.supertrend(bars, 14, 3.0)
    swing_low = bars.low.rolling(SWING_BARS).min()
    swing_high = bars.high.rolling(SWING_BARS).max()
    atr_pct = pd.Series(_rolling_rank((atr / close).values, ATR_PCT_WINDOW), index=bars.index)

    warm = np.arange(len(bars)) >= WARMUP_BARS
    vol_ok = (vol_ratio >= SCAN_VOL_MIN).values
    loosest = min(SCAN_LOOKBACKS)
    long_ok = (warm & vol_ok & (trend > 0) & (rsi >= SCAN_RSI_MIN).values
               & (close == hi_n[loosest]).values)
    short_ok = (warm & vol_ok & (trend < 0) & (rsi <= 100 - SCAN_RSI_MIN).values
                & (close == lo_n[loosest]).values)

    parts = []
    for side, mask, ext in ((1, long_ok, hi_n), (-1, short_ok, lo_n)):
        if not mask.any():
            continue
        sel = bars.index[mask]
        df = pd.DataFrame({
            "signal_time": sel,
            "decision_time": sel + dur,
            "side": side,
            "close": close[mask].values,
            "atr": atr[mask].values,
            "rsi": rsi[mask].values,
            "vol_ratio": vol_ratio[mask].values,
        })
        for n in SCAN_LOOKBACKS:
            df[f"ext{n}"] = (close[mask] == ext[n][mask]).values
        df["run10_atr"] = (side * (close - close.shift(RUN_BARS)) / atr)[mask].values
        df["atr_pct"] = atr_pct[mask].values
        df["htf_ok"] = _htf_trend(df.decision_time, bars_4h) == side
        df["hour"] = df.decision_time.dt.hour
        df["swing_low"] = swing_low[mask].values
        df["swing_high"] = swing_high[mask].values
        df["st_line"] = st_line[mask].values
        parts.append(df)
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(parts).sort_values("signal_time").reset_index(drop=True)[COLUMNS]


def apply_params(scanned: pd.DataFrame, p: DetectorParams) -> pd.DataFrame:
    """Subset of `scanned` passing `p`; the original index is preserved."""
    if p.lookback not in SCAN_LOOKBACKS:
        raise ValueError(f"lookback {p.lookback} not in scanned lookbacks {SCAN_LOOKBACKS}")
    rsi_ok = np.where(scanned.side == 1, scanned.rsi >= p.rsi_level,
                      scanned.rsi <= 100 - p.rsi_level)
    m = scanned[f"ext{p.lookback}"].astype(bool) & (scanned.vol_ratio >= p.vol_mult) & rsi_ok
    if p.htf_trend:
        m &= scanned.htf_ok.astype(bool)
    if p.max_run_atr is not None:
        m &= scanned.run10_atr <= p.max_run_atr
    if p.hours is not None:
        m &= scanned.hour.isin(p.hours)
    if p.atr_pct_range is not None:
        lo, hi = p.atr_pct_range
        m &= scanned.atr_pct.between(lo, hi)
    return scanned[m]
