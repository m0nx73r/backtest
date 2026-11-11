"""Resolve detector signals into fully costed trades on 1-minute data.

Prices: entry and stop exits pay slippage + taker fee; a take-profit fills exactly at the
target with the maker fee. All R values are per 1 unit of dollar risk (risk_px).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from models.ggshot_v2.config import FEE_MAKER, FEE_TAKER, SLIPPAGE

MAX_ENTRY_DELAY_NS = 5 * 60 * 10**9      # skip a signal whose first bar opens > 5 min late
MIN_STOP_ATR = 1.0
MAX_STOP_ATR = 6.0
FIRST_WINDOW = 43_200                    # minutes (30 days); doubled until resolved

COLUMNS = ["symbol", "tf", "side", "signal_time", "decision_time", "entry_time", "entry_px",
           "stop_px", "target_px", "exit_time", "exit_px", "exit_reason", "risk_px",
           "r_gross", "r_fee", "r_funding", "r_net", "notional_per_risk"]


@dataclass(frozen=True)
class TradeSpec:
    stop_method: str            # "swing" | "supertrend" | "atr"
    stop_k: float               # ATR multiple, used only by "atr"
    target_r: float
    entry: str = "next_open"    # "next_open" | "confirm"
    confirm_minutes: int = 0
    confirm_atr: float = 0.0


def _ns(index):
    """UTC nanosecond int64 array of a datetime index / series."""
    idx = pd.DatetimeIndex(index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.as_unit("ns").asi8


def _first_ge(cummax, x):
    return int(np.searchsorted(cummax, x, side="left"))


def _first_le(cummin, x):
    return int(np.searchsorted(-cummin, -x, side="left"))


def _find_exit(side, ei, stop, target, o, h, l, c):
    """Return (index, reason, raw_price) of the exit for a position entered in bar ei."""
    n = len(o)
    window = FIRST_WINDOW
    while True:
        end = min(ei + window, n)
        hi = np.maximum.accumulate(h[ei:end])
        lo = np.minimum.accumulate(l[ei:end])
        size = end - ei
        if side == 1:
            si, ti = _first_le(lo, stop), _first_ge(hi, target)
        else:
            si, ti = _first_ge(hi, stop), _first_le(lo, target)
        if si < size or ti < size:
            if si <= ti:                                   # stop wins ties
                k = ei + si
                gap = o[k] <= stop if side == 1 else o[k] >= stop
                return k, "SL", (o[k] if gap else stop)
            return ei + ti, "TP", target
        if end == n:
            return n - 1, "END", c[n - 1]
        window *= 2


def resolve_trades(signals, m1, funding, spec, symbol, tf):
    """One row per signal that yields a valid trade, indexed like `signals`."""
    if signals.empty or m1.empty:
        return pd.DataFrame(columns=COLUMNS, index=signals.index[:0])
    ts = _ns(m1.index)
    o, h, l, c = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(ts)
    f_ns = _ns(funding.index)
    f_cum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(funding.to_numpy(float)))])

    dec_ns = _ns(signals["decision_time"])
    sides = signals["side"].to_numpy(int)
    close_s = signals["close"].to_numpy(float)
    atr_s = signals["atr"].to_numpy(float)
    swing = {1: signals["swing_low"].to_numpy(float), -1: signals["swing_high"].to_numpy(float)}
    st_line = signals["st_line"].to_numpy(float)

    rows, keep = [], []
    for p in range(len(signals)):
        side, atr, d = int(sides[p]), atr_s[p], dec_ns[p]
        if not atr > 0:
            continue
        i0 = int(np.searchsorted(ts, d, side="left"))
        if spec.entry == "confirm":
            j1 = int(np.searchsorted(ts, d + spec.confirm_minutes * 60 * 10**9, side="left"))
            if j1 <= i0:
                continue
            trig = close_s[p] + side * spec.confirm_atr * atr
            hit = (h[i0:j1] >= trig) if side == 1 else (l[i0:j1] <= trig)
            if not hit.any():
                continue
            ei = i0 + int(hit.argmax())
            raw = max(trig, o[ei]) if side == 1 else min(trig, o[ei])
        else:
            if i0 >= n or ts[i0] - d > MAX_ENTRY_DELAY_NS:
                continue
            ei, raw = i0, o[i0]
        entry = raw * (1 + side * SLIPPAGE)

        if spec.stop_method == "atr":
            stop = entry - side * spec.stop_k * atr
            if not side * (entry - stop) > 0:
                continue
        else:
            level = swing[side][p] if spec.stop_method == "swing" else st_line[p]
            dist = side * (entry - level)
            if not (dist > 0 and dist <= MAX_STOP_ATR * atr):      # NaN fails too
                continue
            stop = level if dist >= MIN_STOP_ATR * atr else entry - side * MIN_STOP_ATR * atr
        risk = abs(entry - stop)
        target = entry + side * spec.target_r * risk

        k, reason, raw_exit = _find_exit(side, ei, stop, target, o, h, l, c)
        if reason == "TP":
            exit_px, exit_fee = raw_exit, FEE_MAKER
        else:
            exit_px, exit_fee = raw_exit * (1 - side * SLIPPAGE), FEE_TAKER

        a = int(np.searchsorted(f_ns, ts[ei], side="right"))      # funding t > entry_time
        b = int(np.searchsorted(f_ns, ts[k], side="right"))       # ... and t <= exit_time
        r_funding = -side * (f_cum[b] - f_cum[a]) * entry / risk
        r_gross = side * (exit_px - entry) / risk
        r_fee = (FEE_TAKER * entry + exit_fee * exit_px) / risk
        rows.append((symbol, tf, side, signals["signal_time"].iloc[p], signals["decision_time"].iloc[p],
                     m1.index[ei], entry, stop, target, m1.index[k], exit_px, reason, risk,
                     r_gross, r_fee, r_funding, r_gross - r_fee + r_funding, entry / risk))
        keep.append(p)

    return pd.DataFrame(rows, columns=COLUMNS, index=signals.index[keep])
