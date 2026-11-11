"""THROWAWAY SPIKE: test alternative stops/exits on the GG-Shot call entries.

Entry: market order at the open of the first bar that opens after the call was posted
(what a follower could actually do), taker fee. Optional: limit at the near edge E.
ATR = ATR(14) on the last bar closed before the post (no look-ahead).

Each variant = (stop rule, exit rule). R = initial stop distance, so avg R is comparable
across variants with different stop widths (fixed $ risk per trade).

Out-of-sample discipline: variants are RANKED on calls before SPLIT, then the same
variants are reported on calls from SPLIT on. Only the second column says anything.
"""
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trigger_probe import atr, TF_MIN  # noqa: E402

MAKER, TAKER = 0.0002, 0.0005
MAX_HOLD = 300      # bars
SPLIT = "2025-01-01"


def simulate(o, h, l, c, d, entry, stop0, target_r=None, trail_atr=None, atr0=None,
             be_at_r=None, max_hold=MAX_HOLD, use_orig_targets=None, entry_fee=TAKER):
    """Bar-by-bar from bar 0 (entry bar, entered at its open). Stop checked before target.
    Trailing/BE updates computed from a bar's extremes apply from the NEXT bar."""
    risk = abs(entry - stop0)
    if risk <= 0:
        return np.nan, "bad"
    stop = stop0
    tgt = entry + d * target_r * risk if target_r else None
    best = entry
    fee = entry_fee * entry
    n = min(len(c), max_hold)
    for k in range(n):
        # gap through the stop at the open -> fill at the open
        if (o[k] <= stop) if d == 1 else (o[k] >= stop):
            px = o[k]; return (d * (px - entry) - fee - TAKER * px) / risk, "SL"
        if (l[k] <= stop) if d == 1 else (h[k] >= stop):
            return (d * (stop - entry) - fee - TAKER * stop) / risk, ("BE" if abs(stop - entry) < 1e-12 else ("TRAIL" if stop != stop0 else "SL"))
        if tgt is not None and ((h[k] >= tgt) if d == 1 else (l[k] <= tgt)):
            return (d * (tgt - entry) - fee - MAKER * tgt) / risk, "TP"
        best = max(best, h[k]) if d == 1 else min(best, l[k])
        if be_at_r and d * (best - entry) >= be_at_r * risk:
            stop = max(stop, entry) if d == 1 else min(stop, entry)
        if trail_atr:
            cand = best - d * trail_atr * atr0
            stop = max(stop, cand) if d == 1 else min(stop, cand)
    px = c[n - 1]
    return (d * (px - entry) - fee - TAKER * px) / risk, "TIME"


def build_variants():
    V = {}
    stops = {"orig_SL": None, "trendline": "F", "1.0atr": 1.0, "1.5atr": 1.5, "2.0atr": 2.0, "3.0atr": 3.0}
    for sname in stops:
        for tr in (1.0, 1.5, 2.0, 3.0):
            V[f"{sname} | TP {tr}R"] = dict(stop=sname, target_r=tr)
        for tA in (1.5, 2.0, 3.0):
            V[f"{sname} | trail {tA}ATR"] = dict(stop=sname, trail_atr=tA)
            V[f"{sname} | trail {tA}ATR + BE@1R"] = dict(stop=sname, trail_atr=tA, be_at_r=1.0)
        V[f"{sname} | TP 3R + BE@1R"] = dict(stop=sname, target_r=3.0, be_at_r=1.0)
    V["orig_SL | orig scaled (baseline)"] = dict(stop="orig_SL", baseline=True)
    return V, stops


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
    V, stops = build_variants()
    res = []
    for _, r in sig.iterrows():
        p = os.path.join(HERE, "call_candles", f"{r.id}.csv")
        if not os.path.exists(p):
            continue
        cdf = pd.read_csv(p, parse_dates=["open_time"])
        dur = pd.Timedelta(minutes=TF_MIN[r.tf])
        closed = cdf[cdf.open_time + dur <= r.ts]
        after = cdf[cdf.open_time >= r.ts]
        if len(closed) < 50 or len(after) < 20:
            continue
        a0 = atr(cdf.loc[:closed.index[-1]], 14).iloc[-1]
        d = 1 if r.side == "Long" else -1
        o, h, l, c = (after[x].values for x in ("open", "high", "low", "close"))
        entry = o[0]
        row = {"id": r.id, "ts": r.ts, "tf": r.tf, "side": r.side}
        for name, v in V.items():
            s = v["stop"]
            if s == "orig_SL":
                stop0 = r.sl
            elif s == "trendline":
                stop0 = r.z2
            else:
                stop0 = entry - d * stops[s] * a0
            if d * (entry - stop0) <= 0:      # entry already beyond the stop
                row[name] = np.nan; continue
            if v.get("baseline"):
                # channel plan from a market entry: 25% at T1..T4, BE after T1
                risk = abs(entry - stop0); tps = [r.t1, r.t2, r.t3, r.t4]; rem = 1.0; pnl = -TAKER * entry; stp = stop0; hit = 0
                done = False
                for k in range(min(len(c), MAX_HOLD)):
                    if (l[k] <= stp) if d == 1 else (h[k] >= stp):
                        pnl += rem * (d * (stp - entry) - TAKER * stp); done = True; break
                    while hit < 4 and ((h[k] >= tps[hit]) if d == 1 else (l[k] <= tps[hit])):
                        if d * (tps[hit] - entry) > 0:
                            pnl += .25 * (d * (tps[hit] - entry) - MAKER * tps[hit]); rem -= .25
                        hit += 1
                        if hit == 1: stp = entry
                    if rem <= 1e-9: done = True; break
                if not done:
                    pnl += rem * (d * (c[min(len(c), MAX_HOLD) - 1] - entry) - TAKER * c[min(len(c), MAX_HOLD) - 1])
                row[name] = pnl / risk
                continue
            R, _ = simulate(o, h, l, c, d, entry, stop0, v.get("target_r"), v.get("trail_atr"), a0, v.get("be_at_r"))
            row[name] = R
        res.append(row)
    df = pd.DataFrame(res)
    df.to_csv(os.path.join(HERE, "exit_spike.csv"), index=False)
    tr, te = df[df.ts < SPLIT], df[df.ts >= SPLIT]
    print(f"calls: {len(df)}  (before {SPLIT}: {len(tr)}, from {SPLIT}: {len(te)})")

    def stats(x):
        x = x.dropna()
        pf = x[x > 0].sum() / -x[x < 0].sum() if (x < 0).any() else np.inf
        return len(x), x.mean(), (x > 0).mean(), pf

    rows = []
    for name in V:
        n1, m1, w1, p1 = stats(tr[name]); n2, m2, w2, p2 = stats(te[name])
        rows.append((name, n1, m1, w1, p1, n2, m2, w2, p2))
    t = pd.DataFrame(rows, columns=["variant", "n_in", "avgR_in", "win_in", "PF_in", "n_out", "avgR_out", "win_out", "PF_out"])
    t = t.sort_values("avgR_in", ascending=False)
    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)
    print(t.round(3).to_string(index=False))
    print("\nTop 5 by in-sample avg R -> out-of-sample:")
    print(t.head(5)[["variant", "avgR_in", "avgR_out", "PF_out", "n_out"]].round(3).to_string(index=False))
    best = t.iloc[0].variant
    print(f"\nBest in-sample variant '{best}' out-of-sample by tf:")
    print(te.groupby("tf")[best].agg(["size", "mean"]).round(3))


if __name__ == "__main__":
    main()
