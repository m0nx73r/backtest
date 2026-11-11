"""Backtest metrics, Monte-Carlo challenge pass rate, robustness checks and the final verdict."""

import numpy as np
import pandas as pd

from .config import (ACCOUNT, BOOTSTRAP_GATE, BOOTSTRAP_RUNS, FLOOR, MAX_COIN_SHARE, MAX_DD,
                     MIN_OOS_TRADES, MIN_WIN_RATE, PASS_LEVEL, RISK_USD, TOP_TRADES_REMOVED)
from .portfolio import challenge_outcome, equity_curve


def summarize(selected: pd.DataFrame, risk_usd: float) -> dict:
    """Headline statistics of the selected trades; max_dd_pct is closed-equity peak-to-trough / peak."""
    n = len(selected)
    challenge = challenge_outcome(selected, risk_usd)
    if n == 0:
        return {"n": 0, "win_rate": float("nan"), "avg_r": float("nan"), "pf": 0.0, "total_usd": 0.0,
                "max_dd_pct": 0.0, "peak_notional_usd": 0.0, "challenge": challenge}
    r = selected["r_net"].to_numpy(dtype=float)
    pnl = r * risk_usd
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float("inf") if losses == 0 and gains > 0 else (gains / losses if losses > 0 else 0.0)
    ec = equity_curve(selected, risk_usd)
    equity = np.concatenate([[ACCOUNT], ec["closed_equity"].to_numpy()])
    peak = np.maximum.accumulate(equity)
    return {"n": n, "win_rate": float((r > 0).mean()), "avg_r": float(r.mean()), "pf": float(pf),
            "total_usd": float(pnl.sum()), "max_dd_pct": float(((peak - equity) / peak).max()),
            "peak_notional_usd": float(ec["open_notional_usd"].max()), "challenge": challenge}


def bootstrap_pass_rate(r_net: np.ndarray, risk_usd: float, runs: int = BOOTSTRAP_RUNS,
                        seed: int = 0, max_trades: int = 5000, chunk: int = 256) -> float:
    """Share of runs that reach PASS_LEVEL before FLOOR (closed equity) within ``max_trades`` draws.

    Each run draws trades with replacement in sequence from ACCOUNT; undecided runs count as not passed.
    Vectorised: trades are drawn in chunks for all still-running runs at once.
    """
    pnl = np.asarray(r_net, dtype=float) * risk_usd
    if runs <= 0 or len(pnl) == 0:
        return 0.0
    rng = np.random.default_rng(seed)
    equity = np.full(runs, ACCOUNT)
    active = np.arange(runs)
    passed = 0
    drawn = 0
    while len(active) and drawn < max_trades:
        step = min(chunk, max_trades - drawn)
        path = equity[active, None] + np.cumsum(pnl[rng.integers(0, len(pnl), (len(active), step))], axis=1)
        hit_pass, hit_fail = path >= PASS_LEVEL, path <= FLOOR
        first_pass = np.where(hit_pass.any(axis=1), hit_pass.argmax(axis=1), step)
        first_fail = np.where(hit_fail.any(axis=1), hit_fail.argmax(axis=1), step)
        passed += int((first_pass < first_fail).sum())
        undecided = (first_pass == step) & (first_fail == step)
        equity[active[undecided]] = path[undecided, -1]
        active = active[undecided]
        drawn += step
    return passed / runs


def robustness(selected: pd.DataFrame, risk_usd: float) -> dict:
    """Sample size, profit without the best trades, and single-coin dependence."""
    n = len(selected)
    pnl = selected["r_net"].astype(float) * risk_usd
    total = float(pnl.sum())
    wo_top = float(np.sort(pnl.to_numpy())[: max(n - TOP_TRADES_REMOVED, 0)].sum())
    share = 0.0
    if total > 0:
        share = float(pnl.groupby(selected["symbol"]).sum().max() / total)
    return {"n_ok": bool(n >= MIN_OOS_TRADES), "wo_top_ok": bool(wo_top > 0),
            "max_coin_share": share, "coin_ok": bool(share <= MAX_COIN_SHARE)}


def breakdown(selected: pd.DataFrame, by: str, risk_usd: float = RISK_USD) -> pd.DataFrame:
    """n, win_rate, avg_r, total_usd per symbol / tf / side / year (of decision_time)."""
    key = selected["decision_time"].dt.year if by == "year" else selected[by]
    g = selected.assign(_win=(selected["r_net"] > 0).astype(float)).groupby(key)
    return pd.DataFrame({"n": g["r_net"].size(), "win_rate": g["_win"].mean(),
                         "avg_r": g["r_net"].mean(), "total_usd": g["r_net"].sum() * risk_usd})


def verdict(summary: dict, robust: dict, boot: float) -> dict:
    """One boolean per acceptance gate plus ``passed`` (all gates)."""
    gates = {"win_rate": bool(summary["win_rate"] >= MIN_WIN_RATE),
             "max_dd": bool(summary["max_dd_pct"] < MAX_DD),
             "challenge": summary["challenge"]["passed"] is True,
             "bootstrap": bool(boot >= BOOTSTRAP_GATE),
             "n_ok": bool(robust["n_ok"]), "wo_top_ok": bool(robust["wo_top_ok"]),
             "coin_ok": bool(robust["coin_ok"])}
    gates["passed"] = all(gates.values())
    return gates
