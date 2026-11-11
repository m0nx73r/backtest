"""Compare the replayed outcome of each call with what the channel itself claimed in replies.

Claims are follow-up messages that reply (directly or through a chain of replies) to a call,
or '#Report' posts naming the same pair/timeframe within 3 days. The highest target count
mentioned is taken as the claim."""
import os, re, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WORDS = {"first": 1, "one": 1, "two": 2, "three": 3, "four": 4, "all": 4, "almost all": 3, "almost three": 2}


def claimed_level(text):
    t = text.lower()
    best = 0
    for m in re.finditer(r"(almost all|almost three|first|one|two|three|four|all)\s+targets?\s+(done|reached|hit)", t):
        best = max(best, WORDS[m.group(1)])
    for m in re.finditer(r"\btp\s*([1-4])\b", t):
        best = max(best, int(m.group(1)))
    return best


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    msgs = pd.read_csv(os.path.join(HERE, "tg_messages.csv"), parse_dates=["ts"])
    msgs.text = msgs.text.fillna("")
    sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
    out = pd.read_csv(os.path.join(HERE, "call_outcomes.csv"))
    call_ids = set(sig.id)
    parent = dict(zip(msgs.id, msgs.reply_to))

    def root(mid, depth=0):
        while depth < 20 and mid in parent and pd.notna(parent[mid]):
            mid = int(parent[mid]); depth += 1
            if mid in call_ids:
                return mid
        return mid if mid in call_ids else None

    claims = {}
    for _, m in msgs.iterrows():
        lvl = claimed_level(m.text)
        if not lvl:
            continue
        rid = root(m.id) if pd.notna(m.reply_to) else None
        if rid is None and "#Report" in m.text:
            h = re.search(r"#(\w+?)\s+(\w+)\s*\|", m.text)
            if h:
                c = sig[(sig.pair == h.group(1)) & (sig.tf == h.group(2)) & (sig.ts <= m.ts) & (sig.ts > m.ts - pd.Timedelta(days=3))]
                if len(c):
                    rid = int(c.iloc[-1].id)
        if rid is not None:
            claims[rid] = max(claims.get(rid, 0), lvl)
    out["claimed"] = out.id.map(claims)
    f = out[out.claimed.notna() & out.edge_filled]
    print(f"calls with a target claim: {out.claimed.notna().sum()} of {len(out)} (filled at E: {len(f)})")
    agree = (f.edge_max_tp >= f.claimed)
    print(f"replay reaches the claimed target too: {agree.mean():.3f}  ({agree.sum()}/{len(f)})")
    print("replay result for claimed calls:", f.edge_max_tp.value_counts().sort_index().to_dict())
    print("avg R (scaled plan): claimed calls %+.3f | unclaimed calls %+.3f"
          % (f.edge_scaled_R.mean(), out[out.claimed.isna() & out.edge_filled].edge_scaled_R.mean()))
    agree2 = (f.edge_max_tp_nobe >= f.claimed)
    print(f"...counting targets until the ORIGINAL stop (no breakeven): {agree2.mean():.3f}  ({agree2.sum()}/{len(f)})")
    later_sl = f[(f.edge_max_tp_nobe >= 1) & (f.edge_t4_all_exit == "SL")]
    print(f"claimed calls that hit T1+ and later hit the original stop: {len(later_sl)}")
    bad = f[~agree][["id", "pair", "tf", "side", "claimed", "edge_max_tp", "edge_scaled_exit"]]
    print("\nclaimed but not reproduced (first 15):\n", bad.head(15).to_string(index=False))
    out.to_csv(os.path.join(HERE, "call_outcomes_claims.csv"), index=False)


if __name__ == "__main__":
    main()
