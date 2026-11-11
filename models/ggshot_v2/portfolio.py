"""Portfolio selection (slot / one-per-coin limits) and challenge pass/fail evaluation."""

import pandas as pd

from .config import ACCOUNT, COINS, FLOOR, MAX_OPEN, PASS_LEVEL, TIMEFRAMES

EVENT_COLUMNS = ["time", "kind", "closed_equity", "open_risk_usd", "open_notional_usd"]


def select_trades(trades: pd.DataFrame, max_open: int = MAX_OPEN) -> pd.DataFrame:
    """Greedy accept in (entry_time, timeframe rank, coin rank) order.

    A trade is open at t when entry_time <= t < exit_time. A candidate is accepted when fewer than
    ``max_open`` accepted trades are open at its entry_time and none of them is on the same symbol.
    Returns the accepted rows (original index kept) in processing order; the input is not mutated.
    """
    tf_rank = {tf: i for i, tf in enumerate(TIMEFRAMES)}
    coin_rank = {c: i for i, c in enumerate(COINS)}
    order = sorted(
        range(len(trades)),
        key=lambda i: (trades["entry_time"].iloc[i],
                       tf_rank.get(trades["tf"].iloc[i], len(tf_rank)),
                       coin_rank.get(trades["symbol"].iloc[i], len(coin_rank)), i))
    open_trades = []  # (exit_time, symbol) of accepted trades
    accepted = []
    for i in order:
        entry = trades["entry_time"].iloc[i]
        symbol = trades["symbol"].iloc[i]
        open_trades = [o for o in open_trades if o[0] > entry]
        if len(open_trades) < max_open and all(o[1] != symbol for o in open_trades):
            accepted.append(i)
            open_trades.append((trades["exit_time"].iloc[i], symbol))
    return trades.iloc[accepted].copy()


def equity_curve(selected: pd.DataFrame, risk_usd: float, start: float = ACCOUNT) -> pd.DataFrame:
    """Event table (entries and exits) with closed equity and open risk/notional after each event.

    Exits are processed before entries at equal timestamps.
    """
    events = []  # (time, kind_rank, seq, kind, pnl, risk, notional)
    for seq, row in enumerate(selected.itertuples(index=False)):
        notional = row.notional_per_risk * risk_usd
        events.append((row.entry_time, 1, seq, "entry", 0.0, risk_usd, notional))
        events.append((row.exit_time, 0, seq, "exit", row.r_net * risk_usd, -risk_usd, -notional))
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
