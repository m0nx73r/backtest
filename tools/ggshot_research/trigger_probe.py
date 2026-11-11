"""Probe what defines a GG-Shot call at the moment it fires.

For each call, take the last bar CLOSED before the post time ("signal bar") and measure:
  * where the near edge E sits vs that bar's close / high / low
  * step S and zone width vs ATR(n)  -> is S a fixed ATR multiple?
  * far edge F (Trend-Line) vs Supertrend(atr_len, mult) lines -> which params match?
  * whether a Supertrend direction flip happened in the last few bars
  * RSI(14) at the signal bar
"""
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def atr(df, n):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df, n, mult):
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
    return line, trend


def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
    ST = [(n, m) for n in (10, 14, 20) for m in (1.0, 1.5, 2.0, 2.5, 3.0)]
    rows = []
    for _, r in sig.iterrows():
        p = os.path.join(HERE, "call_candles", f"{r.id}.csv")
        if not os.path.exists(p):
            continue
        c = pd.read_csv(p, parse_dates=["open_time"])
        dur = pd.Timedelta(minutes=TF_MIN[r.tf])
        closed = c[c.open_time + dur <= r.ts]
        if len(closed) < 100:
            continue
        i = closed.index[-1]
        d = 1 if r.side == "Long" else -1
        E, F = r.z1, r.z2
        S = (r.t1 - E) * d
        bar = c.loc[i]
        o = {"id": r.id, "tf": r.tf, "side": r.side,
             "lag_min": (r.ts - (bar.open_time + dur)).total_seconds() / 60,
             "E_vs_close_pct": (E - bar.close) / bar.close * 100,
             "E_eq_close": np.isclose(E, bar.close, rtol=2e-4),
             "E_eq_any_recent_close": bool(np.isclose(c.close.loc[i - 5:i].values, E, rtol=2e-4).any()),
             "rsi": rsi(c.close).loc[i]}
        for n in (10, 14, 20):
            a = atr(c.loc[:i], n).iloc[-1]
            o[f"S_atr{n}"] = S / a
            o[f"zone_atr{n}"] = abs(E - F) / a
        for n, m in ST:
            line, trend = supertrend(c.loc[:i], n, m)
            o[f"F_vs_st{n}_{m}"] = (F - line[-1]) / abs(E - F)          # 0 => trend line == supertrend
            o[f"stdir{n}_{m}"] = trend[-1] == d
            flips = np.where(np.diff(trend[-12:]) != 0)[0]
            o[f"stflip{n}_{m}"] = (11 - flips[-1]) if len(flips) else 99   # bars since last flip
        rows.append(o)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "trigger_probe.csv"), index=False)
    print("calls probed:", len(res))
    print("lag (min) after signal-bar close:", res.lag_min.quantile([.1, .5, .9]).round(1).to_dict())
    print("E == signal-bar close:", res.E_eq_close.mean().round(3), "| E == one of last 6 closes:", res.E_eq_any_recent_close.mean().round(3))
    print("E vs close pct:", res.E_vs_close_pct.quantile([.1, .5, .9]).round(3).to_dict())
    for n in (10, 14, 20):
        s, z = res[f"S_atr{n}"], res[f"zone_atr{n}"]
        print(f"ATR{n}: S/ATR median {s.median():.2f} IQR {s.quantile(.25):.2f}-{s.quantile(.75):.2f} cv {s.std()/s.mean():.2f} | "
              f"zone/ATR median {z.median():.2f} IQR {z.quantile(.25):.2f}-{z.quantile(.75):.2f}")
    print("\nSupertrend match (|F-line|/zone < 0.05), direction agrees, flipped within 3 bars:")
    for n, m in ST:
        k = f"{n}_{m}"
        print(f"  ST({n},{m}): match {(res[f'F_vs_st{k}'].abs() < 0.05).mean():.3f}  "
              f"median diff {res[f'F_vs_st{k}'].median():+.2f}  dir_agree {res[f'stdir{k}'].mean():.3f}  "
              f"flip<=3 {(res[f'stflip{k}'] <= 3).mean():.3f}")
    print("\nRSI at signal bar:", res.groupby("side").rsi.describe()[["25%", "50%", "75%"]].round(1).to_dict("index"))


if __name__ == "__main__":
    main()
