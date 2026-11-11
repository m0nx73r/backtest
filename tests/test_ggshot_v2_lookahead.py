"""Real-data look-ahead check: every trade must be decidable from data before its decision time."""

import os

import numpy as np
import pandas as pd
import pytest

from models.ggshot_v2 import data
from models.ggshot_v2.detector import DetectorParams, apply_params, scan
from models.ggshot_v2.trades import TradeSpec, resolve_trades

CACHE = os.path.join(data.DATA_DIR, "cache", "BTCUSDT_1m.npz")
N_SAMPLES = 6


@pytest.mark.skipif(not os.path.exists(CACHE), reason="BTCUSDT 1m cache not built")
def test_trades_are_decidable_at_decision_time():
    m1 = data.load_1m("BTCUSDT")
    funding = data.load_funding("BTCUSDT")
    sc = apply_params(scan(data.resample(m1, "1h"), data.resample(m1, "4h")), DetectorParams())
    trades = resolve_trades(sc, m1, funding, TradeSpec("atr", 2, 2), "BTCUSDT", "1h")
    assert len(trades) >= N_SAMPLES
    picks = np.linspace(0, len(trades) - 1, N_SAMPLES).astype(int)

    for i in picks:
        tr = trades.iloc[i]
        sig = sc.loc[trades.index[i]]
        assert tr.entry_time >= tr.decision_time
        cut = m1[m1.index < tr.decision_time]
        cut_sc = scan(data.resample(cut, "1h"), data.resample(cut, "4h"))
        last = cut_sc.iloc[-1]
        assert last.signal_time == sig.signal_time
        assert last.side == sig.side
        for col in ("close", "atr", "st_line"):
            assert last[col] == pytest.approx(sig[col])
