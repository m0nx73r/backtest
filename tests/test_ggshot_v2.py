"""Tests for the ggshot_v2 backtest package (no network access)."""

import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from models.ggshot_v2 import config, data, indicators as ind  # noqa: E402

HEADER = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,"
          "taker_buy_volume,taker_buy_quote_volume,ignore")


def _minutes(start, n, drop=()):
    """Synthetic 1m OHLCV frame (UTC open-time index) with some minutes removed."""
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 0.1, n))
    df = pd.DataFrame({
        "open": close + rng.normal(0, 0.02, n),
        "high": close + 0.2 + rng.random(n) * 0.1,
        "low": close - 0.2 - rng.random(n) * 0.1,
        "close": close,
        "volume": rng.random(n) * 10 + 1,
    }, index=idx)
    keep = np.ones(n, dtype=bool)
    keep[list(drop)] = False
    return df[keep]


def _kline_rows():
    return [
        "1609459200000,29000.1,29100.0,28900.5,29050.2,10.5,1609459259999,305000.0,100,5.0,150000.0,0",
        "1609459260000,29050.2,29200.0,29000.0,29150.7,12.25,1609459319999,357000.0,120,6.0,170000.0,0",
    ]


def _zip(tmp_path, header, name="BTCUSDT-1m-2021-01"):
    rows = ([HEADER] if header else []) + _kline_rows()
    path = tmp_path / f"{name}-{'h' if header else 'n'}.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name + ".csv", "\n".join(rows) + "\n")
    return str(path)


def test_resample_drops_sparse_and_trailing_bars():
    # 1m bars 00:00-01:44 with minutes 00:10-00:20 missing
    m1 = _minutes("2024-01-01 00:00", 105, drop=range(10, 21))
    bars = data.resample(m1, "30m")
    assert list(bars.index.strftime("%H:%M")) == ["00:30", "01:00"]
    b = bars.loc["2024-01-01 00:30"]
    assert b.open == m1.loc["2024-01-01 00:30"].open and b.close == m1.loc["2024-01-01 00:59"].close
    assert b.high == m1.loc["2024-01-01 00:30":"2024-01-01 00:59"].high.max()
    assert b.volume == m1.loc["2024-01-01 00:30":"2024-01-01 00:59"].volume.sum()


def test_archive_csv_with_and_without_header(tmp_path):
    a = data._read_kline_csv(_zip(tmp_path, header=True))
    b = data._read_kline_csv(_zip(tmp_path, header=False))
    assert a.equals(b)
    assert len(a) == 2 and a.index[0] == pd.Timestamp("2021-01-01", tz="UTC")
    assert a.iloc[1].close == 29150.7


class _Resp:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code = status
        self.content = content
        self._payload = payload

    def json(self):
        return self._payload


def test_missing_month_is_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(data, "PAUSE", 0.0)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-1m-2021-02.csv", HEADER + "\n" + "\n".join(_kline_rows()) + "\n")

    def fake_get(url, params=None):
        if url.endswith("BTCUSDT-1m-2021-02.zip"):
            return _Resp(200, buf.getvalue())
        if url.startswith("https://fapi.binance.com"):
            return _Resp(200, payload=[])
        return _Resp(404)

    monkeypatch.setattr(data, "_get", fake_get)
    data.download(["BTCUSDT"], "2021-01-01")          # must not raise
    saved = sorted(f for f in os.listdir(tmp_path / "raw" / "BTCUSDT") if f.endswith(".zip"))
    assert saved == ["BTCUSDT-1m-2021-02.zip"]


def test_load_1m_dedups_sorts_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", str(tmp_path))
    raw = tmp_path / "raw" / "BTCUSDT"
    raw.mkdir(parents=True)
    rows = _kline_rows()
    with zipfile.ZipFile(raw / "BTCUSDT-1m-2021-01.zip", "w") as z:
        z.writestr("x.csv", "\n".join([rows[1], rows[0], rows[0]]) + "\n")
    df = data.load_1m("BTCUSDT")
    assert len(df) == 2 and df.index.is_monotonic_increasing and str(df.index.tz) == "UTC"
    assert (tmp_path / "cache" / "BTCUSDT_1m.npz").exists()
    assert data.load_1m("BTCUSDT").equals(df)           # served from cache


def test_load_funding(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", str(tmp_path))
    raw = tmp_path / "raw" / "BTCUSDT"
    raw.mkdir(parents=True)
    with zipfile.ZipFile(raw / "BTCUSDT-fundingRate-2021-01.zip", "w") as z:
        z.writestr("f.csv", "calc_time,funding_interval_hours,last_funding_rate\n"
                            "1609488000000,8,0.0001\n1609516800000,8,-0.00005\n")
    s = data.load_funding("BTCUSDT")
    assert list(s.values) == [0.0001, -0.00005] and str(s.index.tz) == "UTC"


def test_config_constants():
    assert len(config.COINS) == 15 and config.COINS[0] == "BTCUSDT" and config.COINS[-1] == "FILUSDT"
    assert config.TIMEFRAMES == ["1h", "30m"] and config.FEE_TAKER > config.FEE_MAKER


def test_errored_tail_fetch_keeps_existing_tail(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(data, "PAUSE", 0.0)
    raw = tmp_path / "raw" / "BTCUSDT"
    raw.mkdir(parents=True)
    (raw / "tail_1m.csv").write_text("GOOD-KLINES\n")
    (raw / "tail_funding.csv").write_text("GOOD-FUNDING\n")

    def fake_get(url, params=None):
        if url.startswith("https://fapi.binance.com"):
            return None if "klines" in url else _Resp(500)   # retries exhausted / server error
        return _Resp(404)

    monkeypatch.setattr(data, "_get", fake_get)
    data.download(["BTCUSDT"], "2026-10-01")
    assert (raw / "tail_1m.csv").read_text() == "GOOD-KLINES\n"
    assert (raw / "tail_funding.csv").read_text() == "GOOD-FUNDING\n"
    assert not list(raw.glob("*.part"))


def _bars(high=11.0, low=9.0, close=10.0, n=50):
    """Constant-range hourly OHLCV frame."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": 1.0}, index=idx)


def _trend_then_crash():
    """60 rising bars then 20 falling bars, each with a +/-0.5 high-low range."""
    closes = np.concatenate([100 + np.arange(60, dtype=float),
                             159 - 3.0 * np.arange(1, 21)])
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1h", tz="UTC")
    return pd.DataFrame({"open": closes, "high": closes + 0.5, "low": closes - 0.5,
                         "close": closes, "volume": 1.0}, index=idx)


def _random_bars(n, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    open_ = np.concatenate([[close[0]], close[:-1]]) + rng.normal(0, 0.2, n)
    high = np.maximum(open_, close) + rng.random(n) * 0.8
    low = np.minimum(open_, close) - rng.random(n) * 0.8
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.random(n) * 10 + 1}, index=idx)


def test_rsi_extremes_and_atr_constant_range():
    up = pd.Series(np.arange(1, 101, dtype=float))
    assert ind.rsi(up).iloc[-1] == pytest.approx(100.0)
    df = _bars(high=11.0, low=9.0, close=10.0, n=50)          # constant 2.0 range
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_supertrend_flips_on_reversal():
    df = _trend_then_crash()                                   # 60 rising bars then 20 falling
    line, d = ind.supertrend(df, 14, 3.0)
    assert d.iloc[59] == 1 and d.iloc[-1] == -1
    assert (line.iloc[:60][d.iloc[:60] == 1] < df.close.iloc[:60][d.iloc[:60] == 1]).all()


def test_indicators_are_causal():
    df = _random_bars(300, seed=1)
    for f in (lambda x: ind.atr(x), lambda x: ind.rsi(x.close), lambda x: ind.supertrend(x)[0]):
        assert f(df.iloc[:200]).iloc[-1] == pytest.approx(f(df).iloc[199])


# ---------------------------------------------------------------- detector
from models.ggshot_v2 import detector as det  # noqa: E402


def _uptrend_with_breakout(n=200):
    """Noisy uptrend; the last bar is a volume-spike close at a fresh high."""
    rng = np.random.default_rng(5)
    close = 100 + 0.5 * np.arange(n) + rng.normal(0, 0.8, n)
    close[-1] = close[:-1].max() + 3.0
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    vol = np.ones(n)
    vol[-1] = 5.0
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 0.3,
                         "low": np.minimum(open_, close) - 0.3, "close": close,
                         "volume": vol}, index=idx)


def _mirror(df):
    m = df.copy()
    m["open"], m["close"] = 400 - df.open, 400 - df.close
    m["high"], m["low"] = 400 - df.low, 400 - df.high
    return m


def test_scan_long_breakout_detected_and_mirror_short():
    bars = _uptrend_with_breakout()
    s = det.scan(bars, None)
    last = s[s.signal_time == bars.index[-1]]
    assert len(last) == 1 and last.side.iloc[0] == 1 and bool(last.ext30.iloc[0])
    assert last.decision_time.iloc[0] == bars.index[-1] + pd.Timedelta(hours=1)
    s_short = det.scan(_mirror(bars), None)
    assert s_short[s_short.signal_time == bars.index[-1]].side.iloc[0] == -1
    assert (s.signal_time >= bars.index[100]).all()


def test_apply_params_is_a_subset_and_monotone():
    s = det.scan(_random_bars(3000, seed=2), None)
    loose = det.apply_params(s, det.DetectorParams(15, 55, 1.0))
    tight = det.apply_params(s, det.DetectorParams(30, 70, 2.0))
    assert set(tight.index) <= set(loose.index) and len(tight) < len(loose)
    hrs = det.apply_params(s, det.DetectorParams(15, 55, 1.0, hours=(0, 1, 2)))
    assert set(hrs.index) <= set(loose.index) and hrs.hour.isin([0, 1, 2]).all()


def test_scan_is_decidable_at_decision_time():
    bars = _random_bars(2000, seed=3)
    s = det.scan(bars, None)
    cols = ["side", "close", "rsi", "vol_ratio", "swing_low", "st_line", "atr_pct"]
    for _, row in s.sample(5, random_state=0).iterrows():
        cut = det.scan(bars[bars.index <= row.signal_time], None)
        assert cut.iloc[-1][cols].equals(row[cols])


def test_htf_filter_uses_only_closed_4h_bars():
    bars = _uptrend_with_breakout()
    t = bars.index[-1] + pd.Timedelta(hours=1)               # decision time of the breakout bar
    idx4 = pd.date_range(t - pd.Timedelta(hours=4 * 80), t - pd.Timedelta(hours=4), freq="4h")
    c4 = 100 + np.arange(len(idx4), dtype=float)             # rising: EMA20 > EMA50

    def frame(closes, index):
        return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                             "volume": 1.0}, index=index)

    def htf_at_last(h4):
        s = det.scan(bars, h4)
        return bool(s[s.signal_time == bars.index[-1]].htf_ok.iloc[0])

    h4 = frame(c4, idx4)
    assert h4.index[-1] + pd.Timedelta(hours=4) == t         # last bar closes exactly at t
    assert htf_at_last(h4)
    # a 4h bar opened at t-1h closes after t: its crash must not change htf_ok
    late = frame(np.array([1.0]), [t - pd.Timedelta(hours=1)])
    assert htf_at_last(pd.concat([h4, late]))
    # the same crash on a bar that has closed by t does flip it
    crash = c4.copy()
    crash[-30:] = 1.0
    assert not htf_at_last(frame(crash, idx4))
    # no 4h data, or none closed yet, gives False
    assert not det.scan(bars, None).htf_ok.any()
    assert not htf_at_last(frame(np.array([100.0]), [t - pd.Timedelta(hours=1)]))


# ------------------------------------------------------------------- trades

from models.ggshot_v2 import trades  # noqa: E402

T0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")
SLIP, TAKER, MAKER = 0.0002, 0.0005, 0.0002


def _sig(side=1, close=100.0, atr=1.0, start=T0, **kw):
    row = dict(signal_time=start - pd.Timedelta(hours=1), decision_time=start, side=side,
               close=close, atr=atr, swing_low=np.nan, swing_high=np.nan, st_line=np.nan)
    row.update(kw)
    return pd.DataFrame([row])


def _m1_bars(bars, start=T0):
    """1m frame from explicit (open, high, low, close) tuples, one per minute."""
    idx = pd.date_range(start, periods=len(bars), freq="1min", tz="UTC")
    o, h, l, c = zip(*bars)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": np.ones(len(bars))}, index=idx)


def _m1_path(closes, start=T0):
    """Minute i opens at the previous close (the first at closes[0]) and closes at closes[i]."""
    bars, prev = [], closes[0]
    for c in closes:
        bars.append((prev, max(prev, c), min(prev, c), c))
        prev = c
    return _m1_bars(bars, start)


def _no_funding():
    return pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype=float)


def test_long_hits_target_with_exact_costs():
    t = trades.resolve_trades(_sig(side=1, close=100, atr=1.0), _m1_path([100, 100.5, 104.5]),
                              _no_funding(), trades.TradeSpec("atr", 2.0, 2.0), "BTCUSDT", "1h").iloc[0]
    e = 100 * 1.0002
    assert t.entry_px == pytest.approx(e) and t.stop_px == pytest.approx(e - 2.0)
    assert t.target_px == pytest.approx(e + 4.0) and t.risk_px == pytest.approx(2.0)
    assert t.exit_reason == "TP" and t.exit_px == pytest.approx(e + 4.0)
    assert t.exit_time == T0 + pd.Timedelta(minutes=2) and t.entry_time == T0
    assert t.r_gross == pytest.approx(2.0)
    assert t.r_fee == pytest.approx((0.0005 * e + 0.0002 * (e + 4.0)) / 2.0)
    assert t.r_funding == 0.0
    assert t.r_net == pytest.approx(2.0 - t.r_fee)
    assert t.notional_per_risk == pytest.approx(e / 2.0)
    assert (t.symbol, t.tf, t.side) == ("BTCUSDT", "1h", 1)


def test_short_hits_target_mirrored():
    t = trades.resolve_trades(_sig(side=-1), _m1_path([100, 99.5, 95.5]), _no_funding(),
                              trades.TradeSpec("atr", 2.0, 2.0), "BTCUSDT", "1h").iloc[0]
    e = 100 * 0.9998
    assert t.entry_px == pytest.approx(e) and t.stop_px == pytest.approx(e + 2.0)
    assert t.exit_reason == "TP" and t.exit_px == pytest.approx(e - 4.0)
    assert t.r_gross == pytest.approx(2.0)


def test_stop_wins_when_both_in_same_minute():
    bars = [(100, 100, 100, 100), (100, 105, 97, 100)]   # low < stop 98.02 and high > target 104.02
    t = trades.resolve_trades(_sig(), _m1_bars(bars), _no_funding(),
                              trades.TradeSpec("atr", 2.0, 2.0), "X", "1h").iloc[0]
    e = 100.02
    assert t.exit_reason == "SL" and t.exit_px == pytest.approx((e - 2.0) * (1 - SLIP))
    assert t.r_gross == pytest.approx((t.exit_px - e) / 2.0)
    assert t.r_fee == pytest.approx((TAKER * e + TAKER * t.exit_px) / 2.0)


def test_gap_through_stop_fills_at_open():
    bars = [(100, 100, 100, 100), (95, 95.5, 94.5, 95)]    # opens 3 below the 98.02 stop
    t = trades.resolve_trades(_sig(), _m1_bars(bars), _no_funding(),
                              trades.TradeSpec("atr", 2.0, 2.0), "X", "1h").iloc[0]
    assert t.exit_reason == "SL" and t.exit_px == pytest.approx(95 * (1 - SLIP))
    assert t.r_gross == pytest.approx((95 * (1 - SLIP) - 100.02) / 2.0)
    assert t.r_net < -1.0


def test_confirm_entry_triggers_or_skips():
    spec = trades.TradeSpec("atr", 2.0, 2.0, entry="confirm", confirm_minutes=15, confirm_atr=0.5)
    # trigger L = 100.5 reached in minute 7 (open 100 below L -> fills at L)
    t = trades.resolve_trades(_sig(), _m1_path([100] * 7 + [100.6, 100.6, 104.6]), _no_funding(),
                              spec, "X", "1h").iloc[0]
    assert t.entry_time == T0 + pd.Timedelta(minutes=7)
    assert t.entry_px == pytest.approx(100.5 * (1 + SLIP))
    # bar opening already beyond L fills at its open
    bars = [(100, 100, 100, 100)] * 3 + [(101, 101.2, 100.9, 101), (101, 101, 101, 101)]
    t = trades.resolve_trades(_sig(), _m1_bars(bars), _no_funding(), spec, "X", "1h").iloc[0]
    assert t.entry_px == pytest.approx(101 * (1 + SLIP)) and t.entry_time == T0 + pd.Timedelta(minutes=3)
    # never reached -> no row; reached only at minute 15 (outside [0, 15)) -> no row
    assert trades.resolve_trades(_sig(), _m1_path([100] * 30), _no_funding(), spec, "X", "1h").empty
    late = _m1_path([100] * 15 + [100.6] * 5)
    assert trades.resolve_trades(_sig(), late, _no_funding(), spec, "X", "1h").empty
    # short mirror: L = 99.5
    s = trades.resolve_trades(_sig(side=-1), _m1_path([100] * 4 + [99.4, 99.4]), _no_funding(),
                              spec, "X", "1h").iloc[0]
    assert s.entry_px == pytest.approx(99.5 * (1 - SLIP)) and s.entry_time == T0 + pd.Timedelta(minutes=4)


def test_structural_stop_guards():
    m1 = _m1_path([100, 100.5, 101])
    sw = trades.TradeSpec("swing", 0.0, 2.0)
    e = 100.02
    # swing 0.32 ATR away -> widened to 1.0 ATR
    t = trades.resolve_trades(_sig(swing_low=99.7), m1, _no_funding(), sw, "X", "1h").iloc[0]
    assert t.stop_px == pytest.approx(e - 1.0) and t.risk_px == pytest.approx(1.0)
    # swing inside 1..6 ATR is kept as is
    t = trades.resolve_trades(_sig(swing_low=97.02), m1, _no_funding(), sw, "X", "1h").iloc[0]
    assert t.stop_px == pytest.approx(97.02) and t.risk_px == pytest.approx(3.0)
    # above a long entry / 8 ATR away -> no row
    assert trades.resolve_trades(_sig(swing_low=100.5), m1, _no_funding(), sw, "X", "1h").empty
    assert trades.resolve_trades(_sig(swing_low=92.0), m1, _no_funding(), sw, "X", "1h").empty
    st = trades.TradeSpec("supertrend", 0.0, 2.0)
    assert trades.resolve_trades(_sig(st_line=100.5), m1, _no_funding(), st, "X", "1h").empty
    t = trades.resolve_trades(_sig(st_line=98.02), m1, _no_funding(), st, "X", "1h").iloc[0]
    assert t.stop_px == pytest.approx(98.02)
    # short: swing_high 0.52 away -> widened to 1.0 ATR above entry
    t = trades.resolve_trades(_sig(side=-1, swing_high=100.5), _m1_path([100, 99.5, 99]), _no_funding(),
                              sw, "X", "1h").iloc[0]
    assert t.stop_px == pytest.approx(100 * (1 - SLIP) + 1.0)
    assert trades.resolve_trades(_sig(side=-1, swing_high=99.0), _m1_path([100, 99.5, 99]), _no_funding(),
                                 sw, "X", "1h").empty


def _funding_case(side, last_close):
    start = pd.Timestamp("2024-01-01 07:30", tz="UTC")
    m1 = _m1_path([100.0] * 540 + [last_close], start)          # target hit at 16:30
    marks = pd.DatetimeIndex(["2024-01-01 08:00:00.006", "2024-01-01 16:00:00.006",
                              "2024-01-02 00:00:00.006"], tz="UTC")
    fund = pd.Series([0.0001] * 3, index=marks)
    t = trades.resolve_trades(_sig(side=side, start=start), m1, fund,
                              trades.TradeSpec("atr", 2.0, 2.0), "X", "1h").iloc[0]
    assert t.exit_reason == "TP" and t.exit_time == pd.Timestamp("2024-01-01 16:30", tz="UTC")
    return t


def test_funding_charged_only_inside_trade():
    t = _funding_case(1, 104.5)
    assert t.r_funding == pytest.approx(-2 * 0.0001 * t.entry_px / t.risk_px)
    assert t.r_net == pytest.approx(t.r_gross - t.r_fee + t.r_funding)
    s = _funding_case(-1, 95.5)
    assert s.r_funding == pytest.approx(2 * 0.0001 * s.entry_px / s.risk_px)


def test_open_at_data_end_is_closed_as_END():
    t = trades.resolve_trades(_sig(), _m1_path([100, 100.5, 101]), _no_funding(),
                              trades.TradeSpec("atr", 2.0, 2.0), "X", "1h").iloc[0]
    e = 100.02
    assert t.exit_reason == "END" and t.exit_px == pytest.approx(101 * (1 - SLIP))
    assert t.exit_time == T0 + pd.Timedelta(minutes=2)
    assert t.r_gross == pytest.approx((t.exit_px - e) / 2.0)
    assert t.r_fee == pytest.approx((TAKER * e + TAKER * t.exit_px) / 2.0)


def test_search_window_doubles_beyond_30_days():
    closes = [100.0] * 50000 + [104.5]
    t = trades.resolve_trades(_sig(), _m1_path(closes), _no_funding(),
                              trades.TradeSpec("atr", 2.0, 2.0), "X", "1h").iloc[0]
    assert t.exit_reason == "TP" and t.exit_time == T0 + pd.Timedelta(minutes=50000)


def test_missing_minutes_and_index_preserved():
    full = _m1_path([100.0, 100.5, 104.5] * 3 + [104.5] * 20)
    late = full.drop(full.index[:7])                  # first bar opens 7 min after decision
    spec = trades.TradeSpec("atr", 2.0, 2.0)
    assert trades.resolve_trades(_sig(), late, _no_funding(), spec, "X", "1h").empty
    near = full.drop(full.index[:3])                  # 3 min later -> entry uses that bar
    t = trades.resolve_trades(_sig(), near, _no_funding(), spec, "X", "1h").iloc[0]
    assert t.entry_time == T0 + pd.Timedelta(minutes=3)
    sigs = pd.concat([_sig(), _sig(close=1000.0, atr=1.0), _sig(side=-1)], ignore_index=True)
    sigs.index = [10, 20, 30]
    out = trades.resolve_trades(sigs, _m1_path([100, 100.5, 104.5]), _no_funding(), spec, "X", "1h")
    assert list(out.index) == [10, 20, 30]           # all valid (price mismatch is harmless here)
    sw = trades.TradeSpec("swing", 0.0, 2.0)
    sigs["swing_low"] = [99.0, np.nan, np.nan]       # only the first long has a usable stop
    sigs["swing_high"] = [np.nan, np.nan, 101.0]
    out = trades.resolve_trades(sigs, _m1_path([100, 100.5, 104.5]), _no_funding(), sw, "X", "1h")
    assert list(out.index) == [10, 30]


def _funding_trade(start, n_flat, last_close, mark):
    m1 = _m1_path([100.0] * n_flat + [last_close], start)
    fund = pd.Series([0.0001], index=pd.DatetimeIndex([mark], tz="UTC"))
    return trades.resolve_trades(_sig(start=start), m1, fund, trades.TradeSpec("atr", 2.0, 2.0),
                                 "X", "1h").iloc[0]


def test_funding_minute_floor_entry_on_mark_not_charged():
    # entry bar opens exactly on the 08:00 mark (stamped 08:00:00.006): position opens after settlement
    t = _funding_trade(pd.Timestamp("2024-01-01 08:00", tz="UTC"), 30, 104.5, "2024-01-01 08:00:00.006")
    assert t.entry_time == pd.Timestamp("2024-01-01 08:00", tz="UTC") and t.exit_reason == "TP"
    assert t.r_funding == 0.0


def test_funding_minute_floor_exit_inside_mark_minute_charged():
    t = _funding_trade(pd.Timestamp("2024-01-01 07:30", tz="UTC"), 30, 104.5, "2024-01-01 08:00:00.006")
    assert t.exit_time == pd.Timestamp("2024-01-01 08:00", tz="UTC") and t.exit_reason == "TP"
    assert t.r_funding == pytest.approx(-0.0001 * t.entry_px / t.risk_px)


def test_confirm_stop_on_entry_bar_fills_at_stop_not_prior_open():
    spec = trades.TradeSpec("atr", 0.4, 2.0, entry="confirm", confirm_minutes=5, confirm_atr=0.5)
    # L = 100.5, entry 100.5*1.0002, stop = entry - 0.4; bar opens 100 (< stop) before the trigger
    bars = [(100, 100.6, 99.0, 100.3), (100.3, 100.3, 100.3, 100.3)]
    t = trades.resolve_trades(_sig(), _m1_bars(bars), _no_funding(), spec, "X", "1h").iloc[0]
    e = 100.5 * (1 + SLIP)
    assert t.entry_px == pytest.approx(e) and t.exit_reason == "SL"
    assert t.exit_px == pytest.approx((e - 0.4) * (1 - SLIP))


# ---------------------------------------------------------------- portfolio
from models.ggshot_v2 import portfolio  # noqa: E402

P0 = pd.Timestamp("2024-03-01 00:00", tz="UTC")


def _t(symbol, tf, entry_min, exit_min, r_net=1.0, npr=50.0):
    """Minimal trade row; times are minutes after P0."""
    return {"symbol": symbol, "tf": tf, "entry_time": P0 + pd.Timedelta(minutes=entry_min),
            "exit_time": P0 + pd.Timedelta(minutes=exit_min), "r_net": r_net,
            "notional_per_risk": npr}


def _frame(rows, index=None):
    return pd.DataFrame(rows, index=index)


def _cands():
    # 5 coins enter at minute 60 (given in scrambled order) + a second BTC trade while BTC is open
    rows = [_t("XRPUSDT", "1h", 60, 120), _t("SOLUSDT", "1h", 60, 120), _t("BNBUSDT", "1h", 60, 120),
            _t("ETHUSDT", "1h", 60, 120), _t("BTCUSDT", "1h", 60, 120),
            _t("BTCUSDT", "1h", 90, 150)]
    return _frame(rows)


def test_max_three_open_and_one_per_coin():
    sel = portfolio.select_trades(_cands())
    assert len(sel) == 3 and list(sel.symbol) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]  # coin order tie-break
    # the second BTC trade is rejected on its own (same coin open), even with free slots
    sel2 = portfolio.select_trades(_frame([_t("BTCUSDT", "1h", 60, 120), _t("BTCUSDT", "1h", 90, 150)]))
    assert len(sel2) == 1 and sel2.iloc[0].entry_time == P0 + pd.Timedelta(minutes=60)


def test_1h_beats_30m_on_same_close():
    # BTC/30m listed first and has the better coin rank, but 1h outranks it; one slot only
    rows = [_t("BTCUSDT", "30m", 60, 120), _t("ETHUSDT", "1h", 60, 120)]
    sel = portfolio.select_trades(_frame(rows), max_open=1)
    assert len(sel) == 1 and sel.iloc[0].symbol == "ETHUSDT" and sel.iloc[0].tf == "1h"


def test_slot_frees_at_exit_time():
    rows = [_t("BTCUSDT", "1h", 0, 60), _t("ETHUSDT", "1h", 59, 100), _t("SOLUSDT", "1h", 60, 120),
            _t("BTCUSDT", "1h", 60, 90)]
    sel = portfolio.select_trades(_frame(rows), max_open=1)
    # ETH at 59 is blocked (BTC open); at 60 BTC has exited, so the slot is free: BTC (coin rank) wins
    assert [(r.symbol, r.entry_time) for r in sel.itertuples()] == [
        ("BTCUSDT", P0), ("BTCUSDT", P0 + pd.Timedelta(minutes=60))]
    # same coin may re-enter exactly at its own exit time
    rows2 = [_t("BTCUSDT", "1h", 0, 60), _t("BTCUSDT", "1h", 60, 120)]
    assert len(portfolio.select_trades(_frame(rows2))) == 2


def test_select_keeps_index_and_does_not_mutate_input():
    df = _frame([_t("ETHUSDT", "1h", 60, 120), _t("BTCUSDT", "1h", 60, 120), _t("SOLUSDT", "30m", 0, 30)],
                index=[10, 20, 30])
    before = df.copy(deep=True)
    sel = portfolio.select_trades(df)
    assert list(sel.index) == [30, 20, 10]  # entry order, then coin rank
    pd.testing.assert_frame_equal(df, before)


def test_equity_curve_events_and_exit_before_entry():
    rows = [_t("BTCUSDT", "1h", 0, 60, r_net=2.0, npr=50.0), _t("ETHUSDT", "1h", 60, 120, r_net=-1.0, npr=40.0)]
    ec = portfolio.equity_curve(_frame(rows), risk_usd=20.0)
    assert list(ec.columns) == ["time", "kind", "closed_equity", "open_risk_usd", "open_notional_usd"]
    assert list(ec.kind) == ["entry", "exit", "entry", "exit"]  # exit@60 precedes entry@60
    assert list(ec.closed_equity) == pytest.approx([5000.0, 5040.0, 5040.0, 5020.0])
    assert list(ec.open_risk_usd) == pytest.approx([20.0, 0.0, 20.0, 0.0])
    assert list(ec.open_notional_usd) == pytest.approx([1000.0, 0.0, 800.0, 0.0])


def test_challenge_fail_uses_open_risk():
    # one early loss of -12.5 (artificial R) brings closed equity to 4,750, then 3 trades open together
    rows = [_t("BTCUSDT", "1h", 0, 10, r_net=-12.5),
            _t("ETHUSDT", "1h", 20, 200), _t("SOLUSDT", "1h", 30, 200), _t("BNBUSDT", "1h", 40, 200),
            _t("XRPUSDT", "1h", 50, 200)]
    out = portfolio.challenge_outcome(_frame(rows), risk_usd=20.0)
    # 4750 - 20 = 4730, 4750 - 40 = 4710, 4750 - 60 = 4690 <= 4700 -> fail at the third open entry
    assert out == {"passed": False, "time": P0 + pd.Timedelta(minutes=40), "trades_taken": 4}


def test_challenge_pass_on_exit():
    # +1.97R at $20 = +39.4 each: 12 wins = 5,472.8 (not yet), 13th win = 5,512.2
    rows = [_t("BTCUSDT", "1h", 10 * i, 10 * i + 5, r_net=1.97) for i in range(15)]
    out = portfolio.challenge_outcome(_frame(rows), risk_usd=20.0)
    assert out == {"passed": True, "time": P0 + pd.Timedelta(minutes=125), "trades_taken": 13}


def test_challenge_undecided_and_empty():
    rows = [_t("BTCUSDT", "1h", 0, 10, r_net=1.0), _t("ETHUSDT", "1h", 20, 30, r_net=-1.0)]
    out = portfolio.challenge_outcome(_frame(rows), risk_usd=20.0)
    assert out == {"passed": None, "time": None, "trades_taken": 2}
    empty = portfolio.challenge_outcome(_frame(rows).iloc[0:0], risk_usd=20.0)
    assert empty == {"passed": None, "time": None, "trades_taken": 0}
