"""
Correctness tests for the backtest engines: look-ahead, cost accounting and stats.

The look-ahead tests use the core property of a causal backtest:

    A trade entered on bar i must be reproducible from only the candles that
    had CLOSED by bar i's close (its decision time).

So for sampled trades we cut the data at that trade's decision time and require
the truncated run to open the very same trade. Any code path that reads a future
bar (open-time vs close-time mix-ups, swing windows that peek right, global lists
of zones) breaks this.
They need cached candles (python -m tools.fetch_candles) and are skipped otherwise.

Run:  python -m pytest tests -q
"""

import os
import sys
import unittest

import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from core import costs                                   # noqa: E402
from core.analysis import profit_factor, monte_carlo     # noqa: E402
from core.config import FEE_TAKER, FEE_MAKER, OB_SWING_LOOKBACK  # noqa: E402

DATA = os.path.join(REPO_ROOT, "data", "ohlcv", "BTC_USDT")


def _have(*tfs):
    return all(os.path.exists(os.path.join(DATA, f"{tf}.csv")) for tf in tfs)


def _ohlcv(n, freq, start="2026-01-01", seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) + rng.uniform(0, 0.5, n)
    lo = np.minimum(open_, close) - rng.uniform(0, 0.5, n)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close,
                         "volume": rng.uniform(1, 10, n)}, index=idx)


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------

class TestCostHelpers(unittest.TestCase):
    def test_close_time_index_shifts_by_one_bar(self):
        df = _ohlcv(5, "1h")
        out = costs.to_close_time_index(df)
        self.assertEqual(list(out.index - df.index), [pd.Timedelta(hours=1)] * 5)
        self.assertTrue((out.values == df.values).all())
        self.assertEqual(df.index[0], pd.Timestamp("2026-01-01", tz="UTC"))  # input untouched

    def test_round_trip_fees(self):
        fee = costs.round_trip_fees(2.0, 100.0, 110.0, entry_maker=False, exit_maker=True)
        self.assertAlmostEqual(fee, 2 * 100 * FEE_TAKER + 2 * 110 * FEE_MAKER)

    def test_profit_factor_counts_every_trade(self):
        # +100 win, -50 loss, -50 time exit, -3 fee-negative BE
        self.assertAlmostEqual(profit_factor([100, -50, -50, -3]), 100 / 103)
        self.assertEqual(profit_factor([10, 5]), float("inf"))

    def test_monte_carlo_bootstrap_has_spread(self):
        trades = [{"pnl": p} for p in [100, -50] * 20]
        mc = monte_carlo(trades, n_simulations=500)
        # A shuffle would give p5 == p95 (same trades, same sum); a bootstrap must not.
        self.assertLess(mc["p5_equity"], mc["p95_equity"])


class TestOrderBlockTiming(unittest.TestCase):
    def test_confirmation_is_after_swing_window(self):
        import models.backtest_cisd as cisd
        df = _ohlcv(400, "5min", seed=3)
        obs = cisd.find_order_blocks(df, require_full_window=True)
        self.assertTrue(obs, "synthetic data should produce some OBs")
        for o in obs:
            j = df.index.get_loc(o["time"])
            self.assertGreaterEqual(o["confirm_idx"], j + OB_SWING_LOOKBACK)
            self.assertEqual(o["confirm_time"], df.index[o["confirm_idx"]])

    def test_full_window_obs_do_not_depend_on_future_bars(self):
        import models.backtest_cisd as cisd
        df = _ohlcv(400, "5min", seed=4)
        full = {(o["time"], o["type"]) for o in cisd.find_order_blocks(df, require_full_window=True)
                if o["confirm_idx"] < 300}
        cut = {(o["time"], o["type"]) for o in cisd.find_order_blocks(df.iloc[:300], require_full_window=True)}
        self.assertEqual(full, cut)


# ----------------------------------------------------------------------------
# Truncation (look-ahead) tests on real cached data
# ----------------------------------------------------------------------------

def _closed_by(df, dur, t):
    """Rows of an open-time-indexed frame whose bar had closed by time t."""
    return df[df.index + dur <= t]


N_SAMPLED_TRADES = 6


@unittest.skipUnless(_have("5m", "1h", "1d"), "needs data/ohlcv/BTC_USDT 5m/1h/1d (python -m tools.fetch_candles)")
class TestCisdNoLookahead(unittest.TestCase):
    """For sampled trades, cut the data at that trade's decision time (close of its
    entry bar). The truncated run must open the very same trade on its last bar."""

    def test_each_trade_is_decidable_at_its_entry_time(self):
        import io, contextlib
        import models.backtest_cisd as cisd
        with contextlib.redirect_stdout(io.StringIO()):
            ltf = cisd.fetch_ohlcv_full("BTC/USDT", "5m", 0)
            bias = cisd.fetch_ohlcv_full("BTC/USDT", "1h", 0)
            daily = cisd.fetch_ohlcv_full("BTC/USDT", "1d", 0)
        start = ltf.index[-1] - pd.Timedelta(days=75)
        ltf = ltf[ltf.index >= start]
        bias = bias[bias.index >= start - pd.Timedelta(days=10)]

        def run(l, b, d):
            with contextlib.redirect_stdout(io.StringIO()):
                return cisd.simulate_trades(l, b, d, symbol="BTC/USDT", use_pd_array=True,
                                            use_ltf_msb=True, df_daily=d)

        def key(t):
            return (t["Entry Time"], t["direction"], t["Entry $"], t["Initial Stop $"], t["Target $"])

        trades = run(ltf, bias, daily)["trades"]
        # skip the first trade or two: indicator warm-up differs on a shorter series
        sample = trades[2::max(1, (len(trades) - 2) // N_SAMPLED_TRADES)][:N_SAMPLED_TRADES]
        self.assertGreaterEqual(len(sample), 3, "window should contain trades")
        for t in sample:
            T = pd.Timestamp(t["Entry Time"], tz="UTC") + pd.Timedelta(minutes=5)   # decision time
            cut = run(_closed_by(ltf, pd.Timedelta(minutes=5), T),
                      _closed_by(bias, pd.Timedelta(hours=1), T),
                      _closed_by(daily, pd.Timedelta(days=1), T))
            self.assertIsNotNone(cut["open_trade"], f"trade at {t['Entry Time']} needs data after {T}")
            self.assertEqual(key(cut["open_trade"]), key(t))


@unittest.skipUnless(_have("4h", "15m"), "needs data/ohlcv/BTC_USDT 4h/15m (python -m tools.fetch_candles)")
class TestLiquidityTransferNoLookahead(unittest.TestCase):
    def test_each_trade_is_decidable_at_its_entry_time(self):
        from models.liquidity_transfer import backtest_liquidity_transfer as lt
        d4 = lt.load_ohlcv("BTC/USDT", "4h")
        d15 = lt.load_ohlcv("BTC/USDT", "15m")
        trades, _ = lt.simulate_liquidity_transfer(d4, d15, "BTC/USDT")
        # only trades that survive their fill bar can be "open" at that bar's close
        alive = [t for t in trades if t.duration_bars > 0]
        sample = alive[2::max(1, (len(alive) - 2) // N_SAMPLED_TRADES)][:N_SAMPLED_TRADES]
        self.assertGreaterEqual(len(sample), 3)
        for t in sample:
            T = pd.Timestamp(t.timestamp, tz="UTC") + pd.Timedelta(minutes=15)
            cut4 = d4[d4["timestamp"] + pd.Timedelta(hours=4) <= T].reset_index(drop=True)
            cut15 = d15[d15["timestamp"] + pd.Timedelta(minutes=15) <= T].reset_index(drop=True)
            _, meta = lt.simulate_liquidity_transfer(cut4, cut15, "BTC/USDT")
            ot = meta["open_trade"]
            self.assertIsNotNone(ot, f"trade at {t.timestamp} needs data after {T}")
            self.assertEqual((ot["entry_time"].strftime("%Y-%m-%d %H:%M"), ot["direction"], round(ot["entry"], 4)),
                             (t.timestamp, t.direction, t.entry))


@unittest.skipUnless(_have("4h", "15m"), "needs cached BTC data")
class TestLiquidityTransferCosts(unittest.TestCase):
    def test_pnl_is_net_of_fees(self):
        from models.liquidity_transfer import backtest_liquidity_transfer as lt
        trades, _ = lt.simulate_liquidity_transfer(lt.load_ohlcv("BTC/USDT", "4h"),
                                                   lt.load_ohlcv("BTC/USDT", "15m"), "BTC/USDT")
        self.assertTrue(trades)
        for t in trades:
            d = 1 if t.direction == "LONG" else -1
            gross = d * (t.exit_price - t.entry) * t.contracts
            self.assertGreater(t.fees, 0)
            # Trade records round contracts to 4 dp, so allow ~0.5% of gross for that
            self.assertAlmostEqual(t.pnl, gross - t.fees, delta=0.05 + 0.005 * abs(gross))
            self.assertAlmostEqual(t.r_multiple, t.pnl / lt.RISK_PER_TRADE_USD, delta=0.01)


if __name__ == "__main__":
    unittest.main()
