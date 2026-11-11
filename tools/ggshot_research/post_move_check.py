"""Does the calls' edge come from price moving between the signal-bar close and the post?
move = (first 1m open after the post - signal-bar close) / ATR(14), in the call's direction.
Outcome: single stop 1.5 ATR / target 2R from the first 1m open after the post (taker in/stop,
maker TP), resolved on 1m then call-TF candles."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); os.chdir(HERE)
from trigger_probe import atr, TF_MIN
import simulate_calls as S
sys.stdout.reconfigure(encoding="utf-8")
MAK, TAK = 0.0002, 0.0005
sig = pd.read_csv("signals.csv", parse_dates=["ts"]); rows = []
for _, r in sig.iterrows():
    p = f"call_candles/{r.id}.csv"
    if not os.path.exists(p): continue
    c = pd.read_csv(p, parse_dates=["open_time"]); dur = pd.Timedelta(minutes=TF_MIN[r.tf])
    closed = c[c.open_time + dur <= r.ts]
    a = S.load_after(r, c)
    if len(closed) < 50 or a is None or len(a) < 10: continue
    i = closed.index[-1]; A = atr(c.loc[:i], 14).iloc[-1]; d = 1 if r.side == "Long" else -1
    e = a.open.iloc[0]; move = d * (e - c.close.loc[i]) / A
    st, tp = e - d * 1.5 * A, e + d * 3.0 * A
    o, h, l = a.open.values, a.high.values, a.low.values; R = np.nan
    for k in range(len(o)):
        if (l[k] <= st) if d == 1 else (h[k] >= st): R = (d * (st - e) - TAK * e - TAK * st) / (1.5 * A); break
        if (h[k] >= tp) if d == 1 else (l[k] <= tp): R = (d * (tp - e) - TAK * e - MAK * tp) / (1.5 * A); break
    rows.append(dict(ts=r.ts, tf=r.tf, move=move, R=R))
f = pd.DataFrame(rows).dropna()
f["bucket"] = pd.cut(f.move, [-9, 0, 0.25, 0.5, 1.0, 9])
print(f.groupby("bucket", observed=True).R.agg(["size", "mean", lambda x: (x > 0).mean()]).round(3))
print("all:", len(f), round(f.R.mean(), 3), "| move median", round(f.move.median(), 2))
