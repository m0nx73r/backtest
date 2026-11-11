"""Replay every GG-Shot call against exchange candles and measure real outcomes.

Rules (conservative):
  * Only bars that OPEN at/after the call's post time are tradable.
  * Entry: limit at the zone's near edge E (or zone midpoint for the 'mid' variant),
    must fill within FILL_BARS bars, otherwise the call is 'no_fill'.
  * Within a bar, the stop is checked before any target (worst case).
  * Exit plans (R = |entry - SL|):
      t1_all   : 100% at T1, else SL
      scaled   : 25% at each of T1..T4; after T1 the stop moves to entry (channel's advice)
      t4_all   : 100% at T4, else SL (no breakeven)
  * Positions still open after the downloaded window are closed at the last close.
  * Fees: maker 0.02% for the limit entry and targets, taker 0.05% for stops / time exits.
"""
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FILL_BARS = 48
MAKER, TAKER = 0.0002, 0.0005
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def run_plan(hi, lo, cl, k0, d, entry, sl, tps, weights, be_after_t1):
    """Simulate one exit plan from fill bar k0. Returns (R net of fees, exit_reason, levels_hit)."""
    risk = abs(entry - sl)
    stop = sl
    remaining = 1.0
    pnl = -MAKER * entry          # entry fee per unit, in price terms (scaled by weight 1)
    hit = 0
    for k in range(k0, len(cl)):
        # fill bar: only targets/stop strictly after the fill are knowable -> still check stop (worst case)
        h, l = hi[k], lo[k]
        if (l <= stop) if d == 1 else (h >= stop):
            pnl += remaining * (d * (stop - entry) - TAKER * stop)
            return pnl / risk, ("BE" if stop == entry else "SL"), hit
        if k == k0:
            continue   # fill bar: can't know if the target came after the fill -> no target credit
        for j in range(hit, len(tps)):
            if (h >= tps[j]) if d == 1 else (l <= tps[j]):
                w = weights[j]
                pnl += w * (d * (tps[j] - entry) - MAKER * tps[j])
                remaining -= w
                hit = j + 1
                if hit == 1 and be_after_t1:
                    stop = entry
            else:
                break
        if remaining <= 1e-9:
            return pnl / risk, f"T{hit}", hit
    pnl += remaining * (d * (cl[-1] - entry) - TAKER * cl[-1])
    return pnl / risk, "OPEN", hit


def load_after(r, c):
    """Tradable bars after the post: 1-minute bars for the first ~25h (if downloaded), then the
    call's own timeframe. Bars must OPEN at/after the post time (nothing before it is tradable)."""
    after_tf = c[c.open_time >= r.ts]
    if after_tf.empty or after_tf.open_time.iloc[0] - r.ts > pd.Timedelta(days=2):
        return None   # relisted / mismatched symbol: candles start long after the call
    p1 = os.path.join(HERE, "call_1m", f"{r.id}.csv")
    if not USE_1M or not os.path.exists(p1):
        return c[c.open_time >= r.ts].reset_index(drop=True)
    m1 = pd.read_csv(p1, parse_dates=["open_time"])
    m1 = m1[m1.open_time >= r.ts]
    if m1.empty:
        return c[c.open_time >= r.ts].reset_index(drop=True)
    tail = c[c.open_time >= m1.open_time.iloc[-1] + pd.Timedelta(minutes=1)]
    return pd.concat([m1, tail], ignore_index=True)


USE_1M = os.environ.get("USE_1M", "1") == "1"


def main():
    sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
    rows = []
    for _, r in sig.iterrows():
        p = os.path.join(HERE, "call_candles", f"{r.id}.csv")
        if not os.path.exists(p):
            continue
        c = pd.read_csv(p, parse_dates=["open_time"])
        d = 1 if r.side == "Long" else -1
        after = load_after(r, c)
        if after is None or len(after) < 10:
            continue
        hi, lo, cl = after.high.values, after.low.values, after.close.values
        fill_window_end = r.ts + pd.Timedelta(minutes=FILL_BARS * TF_MIN[r.tf])
        n_fill = int((after.open_time < fill_window_end).sum())
        tps = [r.t1, r.t2, r.t3, r.t4]
        out = {"id": r.id, "ts": r.ts, "pair": r.pair, "tf": r.tf, "side": r.side,
               "gap_to_E_pct": d * (after.open.iloc[0] - r.z1) / r.z1 * 100}
        for variant, entry in (("edge", r.z1), ("mid", (r.z1 + r.z2) / 2)):
            # fill: long fills when low <= entry; short when high >= entry
            fill = None
            for k in range(n_fill):
                if (lo[k] <= entry) if d == 1 else (hi[k] >= entry):
                    fill = k; break
            out[f"{variant}_filled"] = fill is not None
            if fill is None:
                continue
            o_k = after.open.values[fill]
            if (o_k < entry) if d == 1 else (o_k > entry):
                entry = o_k   # bar opened beyond the limit -> filled at the open (better price)
            for plan, w, be in (("t1_all", [1, 0, 0, 0], False),
                                ("scaled", [.25, .25, .25, .25], True),
                                ("t4_all", [0, 0, 0, 1], False)):
                R, why, hit = run_plan(hi, lo, cl, fill, d, entry, r.sl, tps, w, be)
                out[f"{variant}_{plan}_R"] = R
                out[f"{variant}_{plan}_exit"] = why
                if plan == "scaled":
                    out[f"{variant}_max_tp"] = hit
                if plan == "t4_all":
                    out[f"{variant}_max_tp_nobe"] = hit   # highest target before the ORIGINAL stop
        rows.append(out)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "call_outcomes.csv"), index=False)
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    res = main()
    print("calls simulated:", len(res))
    for v in ("edge", "mid"):
        f = res[res[f"{v}_filled"]]
        print(f"\n== entry at {v}: filled {len(f)}/{len(res)}")
        print("  targets reached before stop (scaled plan):",
              {f"T{k}+": round((f[f'{v}_max_tp'] >= k).mean(), 3) for k in range(1, 5)})
        for plan in ("t1_all", "scaled", "t4_all"):
            R = f[f"{v}_{plan}_R"]
            wins = (R > 0).mean()
            print(f"  {plan:7s} n={len(R)} win%={wins:.3f} avgR={R.mean():+.3f} medR={R.median():+.3f} "
                  f"totalR={R.sum():+.1f} PF={R[R>0].sum()/-R[R<0].sum():.2f}  exits={f[f'{v}_{plan}_exit'].value_counts().to_dict()}")
    print("\nby year (edge, scaled):")
    f = res[res.edge_filled]
    print(f.groupby(pd.to_datetime(f.ts).dt.year).edge_scaled_R.agg(["size", "mean", "sum"]).round(3))
    print("\nby tf (edge, scaled):")
    print(f.groupby("tf").edge_scaled_R.agg(["size", "mean", "sum"]).round(3))
    print("\nby side (edge, scaled):")
    print(f.groupby("side").edge_scaled_R.agg(["size", "mean", "sum"]).round(3))
