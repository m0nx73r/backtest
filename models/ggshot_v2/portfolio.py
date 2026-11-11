"""Portfolio selection (slot / one-per-coin limits) and challenge pass/fail evaluation."""

import numpy as np
import pandas as pd

from .config import ACCOUNT, COINS, FLOOR, MAX_OPEN, PASS_LEVEL, TIMEFRAMES

EVENT_COLUMNS = ["time", "kind", "closed_equity", "open_risk_usd", "open_notional_usd"]


def select_trades(trades: pd.DataFrame, max_open: int = MAX_OPEN) -> pd.DataFrame:
    """Greedy accept in (entry_time, timeframe rank, coin rank) order.

    A trade is open at t when entry_time <= t <= exit_time: exit_time is the minute in which the
    stop/target was hit, and an entry in that minute fills at its open, i.e. before the exit, so an
    exit in minute m frees the slot (and the coin) only for entries after m. A candidate is accepted
    when fewer than ``max_open`` accepted trades are open at its entry_time and none of them is on
    the same symbol.
    Returns the accepted rows (original index kept) in processing order; the input is not mutated.
    """
    tf_rank = {tf: i for i, tf in enumerate(TIMEFRAMES)}
    coin_rank = {c: i for i, c in enumerate(COINS)}
    entry_ns = pd.DatetimeIndex(trades["entry_time"]).asi8
    exit_ns = pd.DatetimeIndex(trades["exit_time"]).asi8
    symbols = trades["symbol"].astype(object).to_numpy()
    tf_key = np.array([tf_rank.get(t, len(tf_rank)) for t in trades["tf"]], dtype=np.int64)
    coin_key = np.array([coin_rank.get(s, len(coin_rank)) for s in symbols], dtype=np.int64)
    order = np.lexsort((np.arange(len(trades)), coin_key, tf_key, entry_ns))
    entry_l, exit_l, sym_l = entry_ns.tolist(), exit_ns.tolist(), symbols.tolist()
    open_trades = []  # (exit_ns, symbol) of accepted trades
    accepted = []
    for i in order.tolist():
        entry, symbol = entry_l[i], sym_l[i]
        open_trades = [o for o in open_trades if o[0] >= entry]   # exit in this minute: still open
        if len(open_trades) < max_open and all(o[1] != symbol for o in open_trades):
            accepted.append(i)
            open_trades.append((exit_l[i], symbol))
    return trades.iloc[accepted].copy()


def equity_curve(selected: pd.DataFrame, risk_usd: float, start: float = ACCOUNT) -> pd.DataFrame:
    """Event table (entries and exits) with closed equity and open risk/notional after each event.

    Entries are processed before exits at equal timestamps (an entry fills at the minute's open,
    before a stop/target hit in that minute), so open risk includes both at that minute.
    """
    events = []  # (time, kind_rank, seq, kind, pnl, risk, notional)
    for seq, row in enumerate(selected.itertuples(index=False)):
        notional = row.notional_per_risk * risk_usd
        events.append((row.entry_time, 0, seq, "entry", 0.0, risk_usd, notional))
        events.append((row.exit_time, 1, seq, "exit", row.r_net * risk_usd, -risk_usd, -notional))
    events.sort(key=lambda e: e[:3])
    out = []
    equity, open_risk, open_notional = start, 0.0, 0.0
    for time, _, _, kind, pnl, d_risk, d_notional in events:
        equity += pnl
        open_risk += d_risk
        open_notional += d_notional
        out.append((time, kind, equity, open_risk, open_notional))
    return pd.DataFrame(out, columns=EVENT_COLUMNS)


def challenge_outcome(selected: pd.DataFrame, risk_usd: float) -> dict:
    """First decisive event: fail if closed equity - open risk <= FLOOR (any event),
    pass if closed equity >= PASS_LEVEL (exits only). passed=None when neither is reached."""
    ec = equity_curve(selected, risk_usd)
    taken = 0
    for ev in ec.itertuples(index=False):
        if ev.kind == "entry":
            taken += 1
        if ev.closed_equity - ev.open_risk_usd <= FLOOR:
            return {"passed": False, "time": ev.time, "trades_taken": taken}
        if ev.kind == "exit" and ev.closed_equity >= PASS_LEVEL:
            return {"passed": True, "time": ev.time, "trades_taken": taken}
    return {"passed": None, "time": None, "trades_taken": taken}
