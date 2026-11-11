"""GG-Shot v2 control test: do the finalists' signals beat flipped and random entries?

For each finalist (read from a finalists.json written by ``python -m models.ggshot_v2.run search``),
on all 15 coins x 30m/1h, compares:
  actual   - the finalist's signals (read from the resolved-trade cache)
  flipped  - the same signal bars with the direction reversed, same stop / target / entry rule
  random   - the same number of bars per (coin, tf) sampled from the scan superset with a random
             side, same stop / target / entry rule; one row per seed
"all" = every signal resolved as a standalone trade (heavily overlapping); "selected" = after the
3-slot / one-per-coin portfolio rule (``portfolio.select_trades``).

Usage (from the repo root; needs data/futures and its npz / trade caches):
    python tools/ggshot_research/control_test.py reports/ggshot_v2/<run>/finalists.json \
        [--seeds 0 1 2] [--workers 4] [--out tools/ggshot_research/control_results.txt]
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.ggshot_v2 import config, data  # noqa: E402
from models.ggshot_v2.detector import DetectorParams, apply_params, scan  # noqa: E402
from models.ggshot_v2.portfolio import select_trades  # noqa: E402
from models.ggshot_v2.search import FEATURES, GRID_TRADE, TRADE_COLUMNS  # noqa: E402
from models.ggshot_v2.store import TradeStore  # noqa: E402
from models.ggshot_v2.trades import TradeSpec, resolve_trades  # noqa: E402

DET_FIELDS = ("lookback", "rsi_level", "vol_mult", "htf_trend", "max_run_atr", "hours", "atr_pct_range")
SPEC_FIELDS = ("stop_method", "stop_k", "target_r", "entry", "confirm_minutes", "confirm_atr")
KEEP = ["symbol", "tf", "side", "decision_time", "entry_time", "exit_time", "r_net"]
SPLIT = pd.Timestamp(config.SPLIT, tz="UTC")


def load_finalists(path):
    out = []
    for f in json.loads(Path(path).read_text()):
        c = f["config"]
        det = {k: c[k] for k in DET_FIELDS}
        for k in ("hours", "atr_pct_range"):
            if det[k] is not None:
                det[k] = tuple(det[k])
        out.append((int(f["k"]), DetectorParams(**det), TradeSpec(**{k: c[k] for k in SPEC_FIELDS})))
    return out


def _controls_for_coin(ci, sym, finalists, seeds):
    """Flipped and random-entry trades of every finalist for one coin (both timeframes)."""
    m1, fu = data.load_1m(sym), data.load_funding(sym)
    b4 = data.resample(m1, "4h")
    res = {}                                   # (k, label) -> list of frames
    for ti, tf in enumerate(config.TIMEFRAMES):
        sc = scan(data.resample(m1, tf), b4)
        for k, det, spec in finalists:
            s = apply_params(sc, det)
            f = s.copy()
            f["side"] = -f["side"]
            res.setdefault((k, "flipped"), []).append(resolve_trades(f, m1, fu, spec, sym, tf)[KEEP])
            for seed in seeds:
                rng = np.random.default_rng([seed, k, ci, ti])
                r = sc.sample(len(s), random_state=int(rng.integers(1 << 31))).copy()
                r["side"] = rng.choice([-1, 1], len(r))
                res.setdefault((k, f"random s{seed}"), []).append(
                    resolve_trades(r, m1, fu, spec, sym, tf)[KEEP])
    return res


def _stats(t):
    if len(t) == 0:
        return 0, float("nan"), float("nan")
    return len(t), float(t.r_net.mean()), float((t.r_net > 0).mean())


def _line(label, t):
    out = []
    for per, m in (("in", t.decision_time < SPLIT), ("out", t.decision_time >= SPLIT)):
        x = t[m]
        sel = select_trades(x)
        n, r, w = _stats(x)
        sn, sr, sw = _stats(sel)
        out.append(f"  {label:12s} {per:3s} all n={n:6d} avgR={r:+.3f} win={w:.3f} | "
                   f"selected n={sn:4d} avgR={sr:+.3f} win={sw:.3f}")
        if label == "actual":
            for side, name in ((1, "longs"), (-1, "shorts")):
                xs, ss = x[x.side == side], sel[sel.side == side]
                n, r, _ = _stats(xs)
                sn, sr, _ = _stats(ss)
                out.append(f"  {'  ' + name:12s} {per:3s} all n={n:6d} avgR={r:+.3f}            | "
                           f"selected n={sn:4d} avgR={sr:+.3f}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("finalists", help="finalists.json of a search run")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "tools/ggshot_research/control_results.txt"))
    args = ap.parse_args(argv)
    t0 = time.time()
    finalists = load_finalists(args.finalists)

    store = TradeStore(ROOT / config.TRADE_CACHE_DIR, GRID_TRADE,
                       [(s, tf) for s in config.COINS for tf in config.TIMEFRAMES],
                       TRADE_COLUMNS + FEATURES)
    actual = {}
    for k, det, spec in finalists:
        actual[k] = apply_params(store[spec], det)[KEEP].reset_index(drop=True)
        if len(actual[k]) == 0:
            raise SystemExit(f"finalist {k}: no cached trades for {spec} (build the trade cache first)")

    parts = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_controls_for_coin, ci, sym, finalists, args.seeds)
                for ci, sym in enumerate(config.COINS)]
        for sym, fut in zip(config.COINS, futs):
            for key, frames in fut.result().items():
                parts.setdefault(key, []).extend(frames)
            print(f"[{time.time() - t0:6.0f}s] {sym} done", flush=True)

    lines = ["GG-Shot v2 control test (tools/ggshot_research/control_test.py)",
             f"finalists: {args.finalists}; random seeds: {args.seeds}; 15 coins x 30m/1h; "
             f"in = decision_time < {config.SPLIT}, out = from {config.SPLIT}",
             "all = every signal resolved as a standalone trade (heavily overlapping); selected = after "
             "the 3-slot / one-per-coin portfolio rule (an exit frees its slot only after its minute)",
             "random = same number of bars per (coin, tf) sampled from the scan superset, random side",
             ""]
    for k, det, spec in finalists:
        lines.append(f"Finalist {k}: lookback {det.lookback}, RSI {det.rsi_level:g}, vol {det.vol_mult:g}; "
                     f"stop {spec.stop_method}{'' if spec.stop_method != 'atr' else f' x {spec.stop_k:g}'}, "
                     f"{spec.target_r:g}R, {spec.entry}"
                     + (f" {spec.confirm_minutes} min / {spec.confirm_atr:g} ATR" if spec.entry == "confirm" else ""))
        lines += _line("actual", actual[k])
        lines += _line("flipped", pd.concat(parts[(k, "flipped")], ignore_index=True))
        for seed in args.seeds:
            lines += _line(f"random s{seed}", pd.concat(parts[(k, f"random s{seed}")], ignore_index=True))
        lines.append("")
    text = "\n".join(lines)
    Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"written to {args.out} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
