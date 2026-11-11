"""Spike: book part of the position at T1 and move the stop to entry (user's management idea)."""
import sys, os
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); os.chdir(HERE)
import simulate_calls as S
sys.stdout.reconfigure(encoding="utf-8")
sig = pd.read_csv("signals.csv", parse_dates=["ts"])
plans = {
 "25% each T1-T4, BE after T1 (channel)": [.25, .25, .25, .25],
 "50% at T1, 50% at T2, BE": [.5, .5, 0, 0],
 "50% at T1, rest T2-T4, BE": [.5, 1/6, 1/6, 1/6],
 "50% at T1, 50% at T4, BE": [.5, 0, 0, .5],
 "75% at T1, 25% at T4, BE": [.75, 0, 0, .25],
 "100% at T1": [1, 0, 0, 0],
}
rows = []
for _, r in sig.iterrows():
    p = f"call_candles/{r.id}.csv"
    if not os.path.exists(p): continue
    a = S.load_after(r, pd.read_csv(p, parse_dates=["open_time"]))
    if a is None or len(a) < 10: continue
    d = 1 if r.side == "Long" else -1
    hi, lo, cl = a.high.values, a.low.values, a.close.values
    n_fill = int((a.open_time < r.ts + pd.Timedelta(minutes=S.FILL_BARS * S.TF_MIN[r.tf])).sum())
    fill = next((k for k in range(n_fill) if (lo[k] <= r.z1 if d == 1 else hi[k] >= r.z1)), None)
    if fill is None: continue
    row = {"ts": r.ts, "tf": r.tf}
    for name, w in plans.items():
        row[name] = S.run_plan(hi, lo, cl, fill, d, r.z1, r.sl, [r.t1, r.t2, r.t3, r.t4], w, True)[0]
    rows.append(row)
df = pd.DataFrame(rows)
print("filled calls:", len(df))
for name in plans:
    x = df[name]; pre = df[df.ts < "2025-01-01"][name]; post = df[df.ts >= "2025-01-01"][name]
    print(f"{name:38s} avgR {x.mean():+.3f}  PF {x[x>0].sum()/-x[x<0].sum():.2f}  losing {(x<0).mean():.0%}  "
          f"| <2025 {pre.mean():+.3f}  2025+ {post.mean():+.3f}")
print("full-stop rate (R <= -0.9):", round((df['100% at T1'] <= -0.9).mean(), 3))
