"""In-sample grid search, finalist selection and the single out-of-sample run.

Selection discipline: every ranking / finalist / filter decision is made on trades with
decision_time < SPLIT only (via ``trades_for(..., "in")``); out-of-sample trades are read once,
after the finalists are fixed, by ``run_out_of_sample``.
"""

import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import data, metrics
from . import store as store_mod
from .config import (BOOTSTRAP_RUNS, COINS, MAX_FINALISTS, MIN_IS_TRADES, REPORT_DIR, RISK_USD,
                     RISK_USD_ALT, SPLIT, TIMEFRAMES, TRADE_CACHE_DIR)
from . import trades as trades_mod
from .store import TradeStore
from .detector import DetectorParams, apply_params, scan
from .portfolio import select_trades
from .trades import COLUMNS as TRADE_COLUMNS, TradeSpec, resolve_trades

_ROOT = Path(__file__).resolve().parents[2]
SPLIT_TS = pd.Timestamp(SPLIT, tz="UTC")

GRID_DETECTOR = [DetectorParams(lookback=lb, rsi_level=float(rsi), vol_mult=vm)
                 for lb in (15, 20, 25, 30) for rsi in (55, 60, 65, 70) for vm in (1.0, 1.5, 2.0)]
_STOPS = [("swing", 0.0), ("supertrend", 0.0), ("atr", 1.5), ("atr", 2.0), ("atr", 3.0), ("atr", 4.0)]
_ENTRIES = [("next_open", 0, 0.0)] + [("confirm", m, a) for m in (5, 15, 30) for a in (0.25, 0.5)]
GRID_TRADE = [TradeSpec(stop, k, float(tr), entry, m, a)
              for stop, k in _STOPS for tr in (2, 3) for entry, m, a in _ENTRIES]

BEST_HOURS = 12          # stage-2 hours filter keeps the leader's best 12 UTC decision hours
TOP_FOR_FILTERS = 5
FILTERS = [("htf_trend", True), ("max_run_atr", 2.0), ("max_run_atr", 3.0), ("hours", BEST_HOURS),
           ("atr_pct_range", (0.2, 0.8)), ("atr_pct_range", (0.0, 0.5)),
           ("atr_pct_range", (0.5, 1.0))]
IN_SAMPLE_GATES = ("win_rate", "max_dd", "challenge", "bootstrap")
FEATURES = ["rsi", "vol_ratio", "ext15", "ext20", "ext25", "ext30", "run10_atr", "atr_pct",
            "htf_ok", "hour"]


def _log(msg, t0):
    print(f"[ggshot_v2 {time.time() - t0:7.1f}s elapsed] {msg}", flush=True)


def _in_period(df, period):
    if period is None:
        return df
    if period == "in":
        return df[df["decision_time"] < SPLIT_TS]
    if period == "out":
        return df[df["decision_time"] >= SPLIT_TS]
    raise ValueError(f"period must be 'in', 'out' or None, not {period!r}")


# --------------------------------------------------------------------------- trades

def _fingerprint(m1, funding):
    """Identity of everything a cached trade depends on besides code: the coin's data and costs."""
    return (str(m1.index[-1]) if len(m1) else None, len(m1),
            str(funding.index[-1]) if len(funding) else None,
            trades_mod.FEE_TAKER, trades_mod.FEE_MAKER, trades_mod.SLIPPAGE)


def _build_coin(sym, specs, timeframes, store_dir, period, loaders, label=""):
    """Scan + resolve + write every not-yet-done (coin, tf) of one symbol; returns small status.

    Top-level so a spawned worker process can import it. Only this coin's 1m data is in memory.
    """
    t0 = time.time()
    load_1m, load_funding = loaders or (data.load_1m, data.load_funding)
    st = TradeStore(store_dir, specs, [(sym, tf) for tf in timeframes], TRADE_COLUMNS + FEATURES,
                    period)
    m1, funding = load_1m(sym), load_funding(sym)
    fp = _fingerprint(m1, funding)
    todo = [tf for tf in timeframes if not st.is_done(sym, tf, fp)]
    for tf in timeframes:
        if tf not in todo:
            _log(f"{label}{sym} {tf}: skip (cached)", t0)
    signals = {}
    if todo:
        bars_4h = data.resample(m1, "4h")
        for tf in todo:
            st.begin(sym, tf)
            sc = scan(data.resample(m1, tf), bars_4h)
            for spec in specs:
                tr = _in_period(resolve_trades(sc, m1, funding, spec, sym, tf), period)
                st.write(sym, tf, spec, tr.join(sc[FEATURES]) if len(tr) else tr.iloc[:0])
            st.finish(sym, tf, fp)
            signals[tf] = len(sc)
            _log(f"{label}{sym} {tf}: {len(sc)} signals x {len(specs)} specs", t0)
        del bars_4h
    del m1, funding
    return {"symbol": sym, "built": signals, "skipped": [tf for tf in timeframes if tf not in todo],
            "seconds": round(time.time() - t0, 1)}


def build_trades(symbols, period=None, specs=GRID_TRADE, timeframes=TIMEFRAMES, store_dir=None,
                 workers=1, loaders=None):
    """Resolved trades of the scan superset, per TradeSpec, across all symbols and timeframes.

    One coin's 1m data is held at a time per process. Each (coin, tf) is scanned once over the
    full history and resolved once per spec; the scan's filter features are joined on so
    ``apply_params`` can narrow the rows per detector config. ``period`` ("in"/"out"/None) keeps
    rows by decision_time.

    Every (coin, tf, spec) frame is written to disk as soon as it is resolved, so nothing
    accumulates in memory and an interrupted build resumes at the first incomplete (coin, tf).
    ``store_dir=None`` uses a temporary directory that lives as long as the returned store.
    ``workers`` > 1 builds one coin per worker process (workers write their own files and return
    only status). ``loaders`` = (load_1m, load_funding), picklable top-level callables, overrides
    the data loaders (used by tests). Returns a ``TradeStore`` (mapping TradeSpec -> DataFrame,
    one spec cached at a time).
    """
    tmp = None
    if store_dir is None:
        tmp = store_mod.temp_root()
        store_dir = tmp.name
    specs, symbols, timeframes = list(specs), list(symbols), list(timeframes)
    store = TradeStore(store_dir, specs, [(s, tf) for s in symbols for tf in timeframes],
                       TRADE_COLUMNS + FEATURES, period)
    store._tmp = tmp
    args = (specs, timeframes, str(store_dir), period, loaders)
    if workers > 1 and len(symbols) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_build_coin, sym, *args, f"[{i}/{len(symbols)}] "): sym
                    for i, sym in enumerate(symbols, 1)}
            failed = None
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:      # other coins keep running; their files stay valid
                    failed = failed or (futs[fut], e)
            if failed:
                raise RuntimeError(f"build failed for {failed[0]}: {failed[1]!r}") from failed[1]
    else:
        for i, sym in enumerate(symbols, 1):
            _build_coin(sym, *args, f"[{i}/{len(symbols)}] ")
    return store


def trades_for(cfg, trades_by_spec, period):
    """Trades of one (DetectorParams, TradeSpec) config, restricted to ``period``."""
    det, spec = cfg
    return _in_period(apply_params(trades_by_spec[spec], det), period)


# --------------------------------------------------------------------------- selection

def _cfg_columns(cfg):
    det, spec = cfg
    return {**asdict(det), **asdict(spec)}


def rank_in_sample(trades_by_cfg, risk_usd=RISK_USD, order=None):
    """Per config (after ``select_trades``): n, win_rate, avg_r, pf, max_dd_pct, challenge.

    ``trades_by_cfg`` is a mapping or an iterable of (cfg, in-sample trades) pairs. Configs with
    n >= MIN_IS_TRADES are ranked by avg_r (``rank`` 1, 2, ...) and listed first; the rest follow
    with rank NaN and are never eligible. ``order`` (a list of cfgs) restores a canonical row order
    before ranking, so the stable sort's tie-breaks do not depend on the iteration order.
    """
    items = trades_by_cfg.items() if hasattr(trades_by_cfg, "items") else trades_by_cfg
    rows, t0 = [], time.time()
    for k, (cfg, df) in enumerate(items, 1):
        s = metrics.summarize(select_trades(df), risk_usd)
        rows.append({"cfg": cfg, **_cfg_columns(cfg), "n": s["n"], "win_rate": s["win_rate"],
                     "avg_r": s["avg_r"], "pf": s["pf"], "max_dd_pct": s["max_dd_pct"],
                     "challenge": s["challenge"]["passed"]})
        if k % 250 == 0:
            _log(f"ranked {k} configs", t0)
    ranked = pd.DataFrame(rows, columns=None if rows else ["cfg", "n", "avg_r"])
    if order is not None and len(ranked):
        pos = {c: i for i, c in enumerate(order)}
        ranked = ranked.iloc[sorted(range(len(ranked)), key=lambda i: pos[ranked["cfg"].iat[i]])]
    return _rank(ranked.reset_index(drop=True))


def _rank(ranked):
    ranked = ranked.copy()
    eligible = ranked["n"] >= MIN_IS_TRADES
    ranked["_e"] = eligible
    ranked = ranked.sort_values(["_e", "avg_r"], ascending=[False, False], kind="stable",
                                na_position="last").drop(columns="_e").reset_index(drop=True)
    n_ok = int(eligible.sum())
    ranked["rank"] = [float(i + 1) if i < n_ok else float("nan") for i in range(len(ranked))]
    return ranked


def pick_finalists(ranked):
    """Best two next_open configs plus the best confirm config, all ranked (eligible)."""
    ok = ranked[ranked["rank"].notna()].sort_values("rank") if len(ranked) else ranked
    nxt = [c for c in ok["cfg"] if c[1].entry == "next_open"][:2] if len(ok) else []
    conf = [c for c in ok["cfg"] if c[1].entry == "confirm"][:1] if len(ok) else []
    return (nxt + conf)[:MAX_FINALISTS]


def in_sample_gates(cfg, trades_by_spec, risk_usd=RISK_USD):
    """metrics.verdict gates that apply in-sample (win_rate, max_dd, challenge, bootstrap)."""
    sel = select_trades(trades_for(cfg, trades_by_spec, "in"))
    s = metrics.summarize(sel, risk_usd)
    boot = metrics.bootstrap_pass_rate(sel["r_net"].to_numpy(float), risk_usd, runs=BOOTSTRAP_RUNS)
    v = metrics.verdict(s, metrics.robustness(sel, risk_usd), boot)
    return {g: v[g] for g in IN_SAMPLE_GATES}


def best_hours(cfg, trades_by_spec, k=BEST_HOURS):
    """The k UTC decision hours with the best in-sample avg R of cfg's selected trades (sorted)."""
    sel = select_trades(trades_for(cfg, trades_by_spec, "in"))
    avg = sel.groupby(sel["decision_time"].dt.hour)["r_net"].mean().sort_values(
        ascending=False, kind="stable")
    return tuple(sorted(int(h) for h in avg.index[:k]))


def filter_variants(ranked, trades_by_spec):
    """Stage 2: each filter option alone on each of the top-5 stage-1 configs; ranked in-sample.

    Returns the ranking rows of the variants that are eligible and beat their base's avg_r.
    """
    top = ranked[ranked["rank"].notna()].sort_values("rank").head(TOP_FOR_FILTERS)
    if top.empty:
        return ranked.iloc[:0]
    hours = best_hours(top["cfg"].iloc[0], trades_by_spec)
    variants, base_r = [], {}
    for (det, spec), r in zip(top["cfg"], top["avg_r"]):
        for field, value in FILTERS:
            v = (replace(det, **{field: hours if field == "hours" else value}), spec)
            if v not in base_r and v[0] != det:
                variants.append(v)
                base_r[v] = r
    vr = rank_in_sample(((v, trades_for(v, trades_by_spec, "in")) for v in variants))
    keep = vr["rank"].notna() & (vr["avg_r"] > vr["cfg"].map(base_r))
    return vr[keep]


# --------------------------------------------------------------------------- out of sample

def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def run_out_of_sample(finalists, trades_by_spec, out_dir=None):
    """Each finalist once on decision_time >= SPLIT at RISK_USD and RISK_USD_ALT.

    Writes ``oos_trades_<k>.csv`` and ``oos_summary.json`` into ``out_dir`` when given.
    Returns one row per (finalist, risk).
    """
    rows, report = [], []
    for k, cfg in enumerate(finalists, 1):
        sel = select_trades(trades_for(cfg, trades_by_spec, "out"))
        if out_dir is not None:
            sel.to_csv(Path(out_dir) / f"oos_trades_{k}.csv", index=False)
        by_risk = {}
        for risk in (RISK_USD, RISK_USD_ALT):
            s = metrics.summarize(sel, risk)
            boot = metrics.bootstrap_pass_rate(sel["r_net"].to_numpy(float), risk, runs=BOOTSTRAP_RUNS)
            rob = metrics.robustness(sel, risk)
            v = metrics.verdict(s, rob, boot)
            br = {by: metrics.breakdown(sel, by, risk_usd=risk).reset_index().to_dict("records")
                  for by in ("symbol", "tf", "side", "year")}
            by_risk[str(risk)] = {"summary": s, "bootstrap": boot, "robustness": rob,
                                  "verdict": v, "breakdown": br}
            rows.append({"k": k, **_cfg_columns(cfg), "risk_usd": risk, "n": s["n"],
                         "win_rate": s["win_rate"], "avg_r": s["avg_r"], "pf": s["pf"],
                         "total_usd": s["total_usd"], "max_dd_pct": s["max_dd_pct"],
                         "challenge": s["challenge"]["passed"], "bootstrap": boot,
                         "passed": v["passed"]})
        report.append({"k": k, "config": _cfg_columns(cfg), "by_risk": by_risk})
    if out_dir is not None:
        (Path(out_dir) / "oos_summary.json").write_text(json.dumps(_jsonable(report), indent=2))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- pipeline

def search(symbols=COINS, grid_detector=GRID_DETECTOR, grid_trade=GRID_TRADE, fresh=False, workers=1):
    """Full pipeline; returns the report folder REPORT_DIR/<timestamp>/.

    Resolved trades are cached under TRADE_CACHE_DIR so a crashed run resumes; ``fresh`` deletes
    that cache first.
    """
    t0 = time.time()
    root = Path(REPORT_DIR) if os.path.isabs(REPORT_DIR) else _ROOT / REPORT_DIR
    out_dir = root / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = Path(TRADE_CACHE_DIR) if os.path.isabs(TRADE_CACHE_DIR) else _ROOT / TRADE_CACHE_DIR
    if fresh and cache.exists():
        shutil.rmtree(cache)
    trades_by_spec = build_trades(symbols, specs=grid_trade, store_dir=cache, workers=workers)
    _log(f"trades built for {len(grid_trade)} specs", t0)

    cfgs = [(d, s) for d in grid_detector for s in grid_trade]       # canonical (tie-break) order
    spec_major = ((d, s) for s in grid_trade for d in grid_detector)  # each spec loaded once
    ranked = rank_in_sample(((c, trades_for(c, trades_by_spec, "in")) for c in spec_major),
                            order=cfgs)
    ranked["stage"] = 1
    _log(f"stage 1 ranked {len(cfgs)} configs, {int(ranked['rank'].notna().sum())} eligible", t0)
    finalists = pick_finalists(ranked)

    gates = {c: in_sample_gates(c, trades_by_spec) for c in finalists}
    if not any(all(g.values()) for g in gates.values()):
        _log("no stage-1 finalist passes the in-sample gates: trying filters", t0)
        variants = filter_variants(ranked, trades_by_spec)
        variants = variants.assign(stage=2)
        ranked = _rank(pd.concat([ranked.drop(columns="rank"), variants.drop(columns="rank")],
                                 ignore_index=True))
        finalists = pick_finalists(ranked)
        gates = {c: in_sample_gates(c, trades_by_spec) for c in finalists}
        _log(f"stage 2 kept {len(variants)} filter variants", t0)

    ranked.drop(columns="cfg").to_csv(out_dir / "in_sample_ranking.csv", index=False)
    stats = ["n", "win_rate", "avg_r", "pf", "max_dd_pct", "challenge", "rank", "stage"]
    row = {c: r for c, r in zip(ranked["cfg"], ranked[stats].to_dict("records"))}
    fin = [{"k": k, "stage": int(row[c]["stage"]), "config": _cfg_columns(c),
            "in_sample": row[c], "in_sample_gates": gates[c]} for k, c in enumerate(finalists, 1)]
    (out_dir / "finalists.json").write_text(json.dumps(_jsonable(fin), indent=2))
    _log(f"{len(finalists)} finalists fixed; running out-of-sample once", t0)

    oos = run_out_of_sample(finalists, trades_by_spec, out_dir)
    if len(oos):
        print(oos[["k", "risk_usd", "n", "win_rate", "avg_r", "max_dd_pct", "challenge",
                   "bootstrap", "passed"]].to_string(index=False), flush=True)
    _log(f"report written to {out_dir}", t0)
    return out_dir
