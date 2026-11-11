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


# ---------------------------------------------------------------- metrics
from models.ggshot_v2 import metrics  # noqa: E402


def _seq(rs, symbols=None, years=None, npr=50.0):
    """Non-overlapping sequential trades (10 min each) with the given r_net values."""
    rows = []
    for i, r in enumerate(rs):
        row = _t(symbols[i] if symbols else "BTCUSDT", "1h", 10 * i, 10 * i + 5, r_net=r, npr=npr)
        row["decision_time"] = (pd.Timestamp(f"{years[i]}-06-01", tz="UTC") if years
                                else row["entry_time"])
        rows.append(row)
    return _frame(rows)


def test_bootstrap_bounds():
    assert metrics.bootstrap_pass_rate(np.full(50, 2.0), 20.0, runs=200) == 1.0
    assert metrics.bootstrap_pass_rate(np.full(50, -1.0), 20.0, runs=200) == 0.0
    zero_edge = np.array([2.0, -1.0, -1.0])  # mean 0 -> about 300/800 = 37.5% reach +500 before -300
    assert 0.2 < metrics.bootstrap_pass_rate(zero_edge, 20.0, runs=2000) < 0.6
    # +1R winners but max_trades too small to reach +500 (needs 25 trades) -> counts as not passed
    assert metrics.bootstrap_pass_rate(np.full(10, 1.0), 20.0, runs=50, max_trades=24) == 0.0
    assert metrics.bootstrap_pass_rate(np.full(10, 1.0), 20.0, runs=50, max_trades=25) == 1.0


def test_bootstrap_deterministic_and_fast():
    import time
    r = np.random.default_rng(3).normal(0.05, 1.2, 5000)
    t0 = time.perf_counter()
    a = metrics.bootstrap_pass_rate(r, 20.0, runs=5000, seed=7)
    elapsed = time.perf_counter() - t0
    assert a == metrics.bootstrap_pass_rate(r, 20.0, runs=5000, seed=7)
    assert 0.0 <= a <= 1.0 and elapsed < 5.0


def test_max_dd_and_pf():
    s = metrics.summarize(_seq([2.0, -1.0, -1.0, 1.0]), 20.0)
    # equity 5000 -> 5040 -> 5020 -> 5000 -> 5020 ; peak 5040, trough 5000
    assert s["n"] == 4 and s["win_rate"] == pytest.approx(0.5) and s["avg_r"] == pytest.approx(0.25)
    assert s["total_usd"] == pytest.approx(20.0) and s["pf"] == pytest.approx(60.0 / 40.0)
    assert s["max_dd_pct"] == pytest.approx(40.0 / 5040.0)
    assert s["peak_notional_usd"] == pytest.approx(1000.0)
    assert s["challenge"] == {"passed": None, "time": None, "trades_taken": 4}
    # a first-trade loss counts against the starting balance as the peak
    assert metrics.summarize(_seq([-1.0]), 20.0)["max_dd_pct"] == pytest.approx(20.0 / 5000.0)


def test_summarize_pf_edges_and_empty():
    assert metrics.summarize(_seq([1.0, 1.0]), 20.0)["pf"] == float("inf")
    assert metrics.summarize(_seq([-1.0, -1.0]), 20.0)["pf"] == 0.0
    e = metrics.summarize(_seq([1.0]).iloc[0:0], 20.0)
    assert e["n"] == 0 and e["total_usd"] == 0.0 and e["pf"] == 0.0 and e["max_dd_pct"] == 0.0
    assert e["peak_notional_usd"] == 0.0 and np.isnan(e["win_rate"]) and np.isnan(e["avg_r"])
    assert e["challenge"]["passed"] is None


def test_robustness_flags_single_coin_dependence():
    # BTC earns 160 of 180 total (8/9) -> coin_ok False; removing the top 5 (all trades) leaves 0 -> wo_top False
    rs = [2.0] * 4 + [1.0]
    syms = ["BTCUSDT"] * 4 + ["ETHUSDT"]
    rb = metrics.robustness(_seq(rs, syms), 20.0)
    assert rb["max_coin_share"] == pytest.approx(8 / 9) and rb["coin_ok"] is False
    assert rb["n_ok"] is False and rb["wo_top_ok"] is False
    # balanced: 100 trades over 5 coins, all +1R -> share 0.2, n ok, still profitable without the top 5
    coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"] * 20
    rb2 = metrics.robustness(_seq([1.0] * 100, coins), 20.0)
    assert rb2["max_coin_share"] == pytest.approx(0.2)
    assert rb2["n_ok"] is True and rb2["wo_top_ok"] is True and rb2["coin_ok"] is True
    # non-positive total -> share 0 and wo_top False
    rb3 = metrics.robustness(_seq([-1.0, 1.0, -1.0]), 20.0)
    assert rb3["max_coin_share"] == 0.0 and rb3["wo_top_ok"] is False


def test_breakdown_groups_by_symbol_and_year():
    sel = _seq([1.0, -1.0, 2.0], ["BTCUSDT", "BTCUSDT", "ETHUSDT"], years=[2023, 2024, 2024])
    by_sym = metrics.breakdown(sel, "symbol")
    assert list(by_sym.columns) == ["n", "win_rate", "avg_r", "total_usd"]
    assert by_sym.loc["BTCUSDT"].tolist() == pytest.approx([2, 0.5, 0.0, 0.0])
    assert by_sym.loc["ETHUSDT"].tolist() == pytest.approx([1, 1.0, 2.0, 40.0])
    by_year = metrics.breakdown(sel, "year")
    assert list(by_year.index) == [2023, 2024]
    assert by_year.loc[2024].tolist() == pytest.approx([2, 0.5, 0.5, 20.0])
    assert metrics.breakdown(sel, "tf").loc["1h", "n"] == 3


def test_verdict_requires_all_gates():
    summary = {"win_rate": 0.45, "max_dd_pct": 0.05, "challenge": {"passed": True}}
    robust = {"n_ok": True, "wo_top_ok": True, "coin_ok": True}
    v = metrics.verdict(summary, robust, 0.7)
    assert v == {"win_rate": True, "max_dd": True, "challenge": True, "bootstrap": True,
                 "n_ok": True, "wo_top_ok": True, "coin_ok": True, "passed": True}
    assert not metrics.verdict({**summary, "win_rate": 0.39}, robust, 0.7)["passed"]
    assert not metrics.verdict({**summary, "max_dd_pct": 0.10}, robust, 0.7)["passed"]
    assert not metrics.verdict({**summary, "challenge": {"passed": None}}, robust, 0.7)["passed"]
    assert not metrics.verdict(summary, robust, 0.64)["passed"]
    for k in ("n_ok", "wo_top_ok", "coin_ok"):
        v = metrics.verdict(summary, {**robust, k: False}, 0.7)
        assert v[k] is False and v["passed"] is False
    assert metrics.verdict({**summary, "win_rate": 0.40}, robust, 0.65)["passed"] is True


# ------------------------------------------------------------------- portfolio speed-up (Task 7)

def _reference_select(trades, max_open=config.MAX_OPEN):
    """Original per-row implementation of portfolio.select_trades (behaviour oracle)."""
    tf_rank = {tf: i for i, tf in enumerate(config.TIMEFRAMES)}
    coin_rank = {c: i for i, c in enumerate(config.COINS)}
    order = sorted(
        range(len(trades)),
        key=lambda i: (trades["entry_time"].iloc[i],
                       tf_rank.get(trades["tf"].iloc[i], len(tf_rank)),
                       coin_rank.get(trades["symbol"].iloc[i], len(coin_rank)), i))
    open_trades, accepted = [], []
    for i in order:
        entry, symbol = trades["entry_time"].iloc[i], trades["symbol"].iloc[i]
        open_trades = [o for o in open_trades if o[0] > entry]
        if len(open_trades) < max_open and all(o[1] != symbol for o in open_trades):
            accepted.append(i)
            open_trades.append((trades["exit_time"].iloc[i], symbol))
    return trades.iloc[accepted].copy()


def test_select_trades_matches_reference_on_random_frames():
    rng = np.random.default_rng(7)
    symbols = config.COINS[:5] + ["ZZZUSDT"]              # includes an unknown coin
    for _ in range(300):
        n = int(rng.integers(1, 40))
        rows = [_t(str(rng.choice(symbols)), str(rng.choice(["1h", "30m", "4h"])), int(e),
                   int(e) + int(rng.integers(1, 120)), r_net=float(rng.normal()))
                for e in rng.integers(0, 40, n) * 10]      # many equal entry times
        df = _frame(rows, index=rng.permutation(1000)[:n])
        mo = int(rng.integers(1, 5))
        pd.testing.assert_frame_equal(portfolio.select_trades(df, max_open=mo),
                                      _reference_select(df, max_open=mo))
    empty = _frame([_t("BTCUSDT", "1h", 0, 10)]).iloc[:0]
    pd.testing.assert_frame_equal(portfolio.select_trades(empty), _reference_select(empty))


# ------------------------------------------------------------------- search (Task 7)

import json  # noqa: E402

from models.ggshot_v2 import search  # noqa: E402
from models.ggshot_v2 import store as store_mod  # noqa: E402

SPLIT_TS = pd.Timestamp(config.SPLIT, tz="UTC")
_SYN_CACHE = {}


def _synthetic_1m(symbol):
    """Trending-regime random walk of 1m bars spanning SPLIT (deterministic per symbol)."""
    if symbol not in _SYN_CACHE:
        rng = np.random.default_rng(sum(map(ord, symbol)))
        idx = pd.date_range("2024-10-20", "2025-02-10", freq="1min", tz="UTC", inclusive="left")
        n = len(idx)
        regime = np.repeat(rng.choice([-1.0, 1.0], n // 2880 + 1), 2880)[:n]
        close = 100 * np.exp(np.cumsum(regime * 0.00004 + rng.normal(0, 0.0008, n)))
        open_ = np.concatenate([[close[0]], close[:-1]])
        wig = np.abs(rng.normal(0, 0.0004, n)) * close
        _SYN_CACHE[symbol] = pd.DataFrame({
            "open": open_, "high": np.maximum(open_, close) + wig,
            "low": np.minimum(open_, close) - wig, "close": close,
            "volume": rng.gamma(2.0, 5.0, n)}, index=idx)
    return _SYN_CACHE[symbol]


def _synthetic_funding(symbol):
    idx = pd.date_range("2024-10-20", "2025-02-10", freq="8h", tz="UTC")
    return pd.Series(0.0001, index=idx, name="funding_rate")


SYN_COINS = ["BTCUSDT", "ETHUSDT"]
TINY_DET = [det.DetectorParams(lookback=15, rsi_level=55.0, vol_mult=1.0)]
TINY_SPECS = [trades.TradeSpec("atr", 2.0, 2.0),
              trades.TradeSpec("atr", 2.0, 2.0, entry="confirm", confirm_minutes=15, confirm_atr=0.25)]


@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    monkeypatch.setattr(search.data, "load_1m", _synthetic_1m)
    monkeypatch.setattr(search.data, "load_funding", _synthetic_funding)
    monkeypatch.setattr(search, "MIN_IS_TRADES", 5)
    monkeypatch.setattr(search, "BOOTSTRAP_RUNS", 200)
    monkeypatch.setattr(search, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(search, "TRADE_CACHE_DIR", str(tmp_path / "trades_cache"))
    return tmp_path


def test_grid_sizes():
    assert len(search.GRID_DETECTOR) == 48 and len(set(search.GRID_DETECTOR)) == 48
    assert len(search.GRID_TRADE) == 84 and len(set(search.GRID_TRADE)) == 84
    assert all(not (p.htf_trend or p.max_run_atr or p.hours or p.atr_pct_range)
               for p in search.GRID_DETECTOR)
    assert sum(s.entry == "next_open" for s in search.GRID_TRADE) == 12


def _ranked(cfgs, avg_rs):
    return pd.DataFrame({"cfg": cfgs, "n": 500, "avg_r": avg_rs,
                         "rank": np.arange(1, len(cfgs) + 1, dtype=float)})


def test_pick_finalists_reserves_confirm_slot():
    d = det.DetectorParams()
    nxt = [(d, trades.TradeSpec("atr", k, 2.0)) for k in (1.5, 2.0, 3.0, 4.0)]
    conf = (d, trades.TradeSpec("atr", 2.0, 2.0, "confirm", 5, 0.25))
    ranked = _ranked(nxt + [conf], [0.5, 0.4, 0.3, 0.2, 0.1])
    assert search.pick_finalists(ranked) == [nxt[0], nxt[1], conf]
    assert len(search.pick_finalists(ranked)) <= config.MAX_FINALISTS
    # no qualifying confirm config -> fewer finalists, never a third next_open
    assert search.pick_finalists(ranked.iloc[:4]) == [nxt[0], nxt[1]]
    unranked = ranked.copy()
    unranked.loc[4, "rank"] = np.nan                      # ineligible rows are never picked
    assert search.pick_finalists(unranked) == [nxt[0], nxt[1]]
    assert search.pick_finalists(ranked.iloc[:0]) == []


def _trade_frame(n, r, start="2022-01-01", symbol="BTCUSDT"):
    """n non-overlapping in-sample trades with constant r_net."""
    ent = pd.Timestamp(start, tz="UTC") + pd.to_timedelta(np.arange(n) * 120, unit="min")
    return pd.DataFrame({"symbol": symbol, "tf": "1h", "side": 1, "decision_time": ent,
                         "entry_time": ent, "exit_time": ent + pd.Timedelta(minutes=60),
                         "r_net": float(r), "notional_per_risk": 50.0})


def test_rank_ignores_configs_below_min_trades():
    d = det.DetectorParams()
    few, many_lo, many_hi = ((d, trades.TradeSpec("atr", k, 2.0)) for k in (1.5, 2.0, 3.0))
    m = config.MIN_IS_TRADES
    ranked = search.rank_in_sample({few: _trade_frame(m - 1, 2.0),
                                    many_lo: _trade_frame(m, 0.1),
                                    many_hi: _trade_frame(m + 10, 0.3)}, config.RISK_USD)
    assert list(ranked["cfg"]) == [many_hi, many_lo, few]
    assert list(ranked["rank"].iloc[:2]) == [1.0, 2.0] and np.isnan(ranked["rank"].iloc[2])
    assert {"n", "win_rate", "avg_r", "pf", "max_dd_pct", "challenge"} <= set(ranked.columns)
    assert list(ranked["n"]) == [m + 10, m, m - 1]
    assert search.pick_finalists(ranked) == [many_hi, many_lo]


def test_build_trades_and_trades_for(synthetic):
    by_spec = search.build_trades(SYN_COINS, specs=TINY_SPECS)
    assert set(by_spec) == set(TINY_SPECS)
    for df in by_spec.values():
        assert df.index.is_unique and len(df) > 0
        assert set(df["symbol"]) == set(SYN_COINS) and set(df["tf"]) == set(config.TIMEFRAMES)
        assert {"ext15", "ext30", "rsi", "vol_ratio", "htf_ok", "run10_atr", "atr_pct",
                "hour"} <= set(df.columns)
        assert (df["decision_time"] >= SPLIT_TS).any() and (df["decision_time"] < SPLIT_TS).any()
    spec = TINY_SPECS[0]
    cfg = (det.DetectorParams(lookback=20, rsi_level=60.0), spec)
    full = det.apply_params(by_spec[spec], cfg[0])
    ins, oos = (search.trades_for(cfg, by_spec, p) for p in ("in", "out"))
    assert len(ins) and len(oos)
    assert (ins["decision_time"] < SPLIT_TS).all() and (oos["decision_time"] >= SPLIT_TS).all()
    assert sorted(ins.index.append(oos.index)) == sorted(full.index)
    assert search.trades_for(cfg, by_spec, None).index.equals(full.index)
    only_in = search.build_trades(SYN_COINS[:1], period="in", specs=TINY_SPECS[:1])
    assert len(only_in[spec]) and (only_in[spec]["decision_time"] < SPLIT_TS).all()


def test_oos_never_feeds_selection(synthetic, monkeypatch):
    calls, built = [], {}
    real_build, real_rank = search.build_trades, search.rank_in_sample
    real_pick, real_for = search.pick_finalists, search.trades_for

    def build_spy(*a, **kw):
        built.update(real_build(*a, **kw))
        return built

    def rank_spy(trades_by_cfg, risk_usd=config.RISK_USD, **kw):
        items = list(trades_by_cfg.items() if hasattr(trades_by_cfg, "items") else trades_by_cfg)
        for _, df in items:
            assert (df["decision_time"] < SPLIT_TS).all()
        calls.append(("rank", len(items)))
        return real_rank(items, risk_usd, **kw)

    def pick_spy(ranked):
        assert "decision_time" not in ranked.columns and {"avg_r", "rank"} <= set(ranked.columns)
        calls.append(("pick",))
        return real_pick(ranked)

    def for_spy(cfg, trades_by_spec, period):
        calls.append(("for", period))
        return real_for(cfg, trades_by_spec, period)

    monkeypatch.setattr(search, "build_trades", build_spy)
    monkeypatch.setattr(search, "rank_in_sample", rank_spy)
    monkeypatch.setattr(search, "pick_finalists", pick_spy)
    monkeypatch.setattr(search, "trades_for", for_spy)
    # force stage 2 so the hours derivation and the filter variants also run through the spies
    monkeypatch.setattr(search, "in_sample_gates", lambda cfg, tbs, risk_usd=config.RISK_USD:
                        {"win_rate": False, "max_dd": True, "challenge": False, "bootstrap": False})
    out = search.search(SYN_COINS, grid_detector=TINY_DET, grid_trade=TINY_SPECS)
    assert any((df["decision_time"] >= SPLIT_TS).any() for df in built.values())  # OOS rows exist
    ranks = [c for c in calls if c[0] == "rank"]
    assert len(ranks) == 2 and ranks[1][1] > 0                # stage 2 ranked filter variants
    last_pick = max(i for i, c in enumerate(calls) if c[0] == "pick")
    outs = [i for i, c in enumerate(calls) if c == ("for", "out")]
    assert outs and min(outs) > last_pick
    assert all(c[1] == "in" for c in calls[:last_pick] if c[0] == "for")
    assert out.exists()


def test_end_to_end_on_synthetic_two_coins(synthetic, capsys):
    out = search.search(SYN_COINS, grid_detector=TINY_DET, grid_trade=TINY_SPECS)
    assert out.parent == synthetic / "reports"
    names = {p.name for p in out.iterdir()}
    assert {"in_sample_ranking.csv", "finalists.json", "oos_summary.json"} <= names
    fin = json.loads((out / "finalists.json").read_text())
    assert 1 <= len(fin) <= config.MAX_FINALISTS
    assert {f"oos_trades_{k}.csv" for k in range(1, len(fin) + 1)} <= names
    ranking = pd.read_csv(out / "in_sample_ranking.csv")
    assert {"lookback", "stop_method", "entry", "n", "avg_r", "rank", "stage"} <= set(ranking.columns)
    summ = json.loads((out / "oos_summary.json").read_text())
    assert len(summ) == len(fin)
    for f in summ:
        assert set(f["by_risk"]) == {str(config.RISK_USD), str(config.RISK_USD_ALT)}
        res = f["by_risk"][str(config.RISK_USD)]
        assert {"summary", "bootstrap", "robustness", "verdict", "breakdown"} <= set(res)
        assert set(res["breakdown"]) == {"symbol", "tf", "side", "year"}
    oos = pd.read_csv(out / "oos_trades_1.csv", parse_dates=["decision_time"])
    assert len(oos) and (oos["decision_time"] >= SPLIT_TS).all()
    assert "elapsed" in capsys.readouterr().out


def test_run_cli_dispatch(monkeypatch, capsys):
    from models.ggshot_v2 import run
    seen = []
    monkeypatch.setattr(run.data, "download", lambda syms, start: seen.append(("dl", syms, start)))
    monkeypatch.setattr(run.search, "search", lambda **kw: seen.append(("search", kw)))
    run.main(["download"])
    run.main(["search"])
    monkeypatch.setattr(run, "sanity", lambda: seen.append(("sanity",)))
    run.main(["sanity"])
    assert seen == [("dl", config.COINS, config.START), ("search", {"fresh": False, "workers": 4}),
                    ("sanity",)]
    with pytest.raises(SystemExit):
        run.main([])


# ------------------------------------------------------------------- disk-backed store (Task 7b)

def _sorted(df):
    return df.sort_values(["symbol", "tf", "decision_time"]).reset_index(drop=True)


def test_store_matches_in_memory_build(synthetic, tmp_path):
    mem = search.build_trades(SYN_COINS, specs=TINY_SPECS)
    disk = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=tmp_path / "st")
    assert len(disk) == 2 and set(disk) == set(TINY_SPECS) and TINY_SPECS[0] in disk
    for spec in TINY_SPECS:
        a, b = _sorted(mem[spec]), _sorted(disk[spec])
        assert disk[spec].index.is_unique and len(b) > 0
        pd.testing.assert_frame_equal(a, b)
    for sym in SYN_COINS:
        for tf in config.TIMEFRAMES:
            assert (tmp_path / "st" / f"{sym}_{tf}" / "_done").is_file()


def test_store_resumes_only_missing_pair(synthetic, tmp_path, monkeypatch):
    sd = tmp_path / "st"
    first = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    ref = {s: _sorted(first[s]) for s in TINY_SPECS}
    d = sd / f"{SYN_COINS[1]}_{config.TIMEFRAMES[0]}"
    for f in d.iterdir():
        f.unlink()
    calls = []
    real = search.resolve_trades

    def spy(sc, m1, funding, spec, sym, tf):
        calls.append((sym, tf, spec))
        return real(sc, m1, funding, spec, sym, tf)

    monkeypatch.setattr(search, "resolve_trades", spy)
    again = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    assert {(c[0], c[1]) for c in calls} == {(SYN_COINS[1], config.TIMEFRAMES[0])}
    assert len(calls) == len(TINY_SPECS)
    for s in TINY_SPECS:
        pd.testing.assert_frame_equal(ref[s], _sorted(again[s]))


def test_store_empty_spec_has_datetime_columns(synthetic, tmp_path):
    never = trades.TradeSpec("atr", 2.0, 1e9)             # target never reached; still resolves
    st = search.build_trades(SYN_COINS[:1], period="in", specs=TINY_SPECS[:1], store_dir=tmp_path / "e")
    for p in (tmp_path / "e").glob("*/*.pkl"):
        pd.read_pickle(p).iloc[:0].to_pickle(p)            # force "no trades" for every file
    st._cache = (None, None)
    df = st[TINY_SPECS[0]]
    assert len(df) == 0 and list(df.columns) == search.TRADE_COLUMNS + search.FEATURES
    for c in ("signal_time", "decision_time", "entry_time", "exit_time"):
        assert str(df[c].dtype) == "datetime64[ns, UTC]"
    assert len(search.trades_for((TINY_DET[0], TINY_SPECS[0]), st, "out")) == 0


def test_interrupted_write_is_redone(synthetic, tmp_path, monkeypatch):
    sd = tmp_path / "st"
    real_write, n = store_mod.TradeStore.write, []

    def flaky(self, sym, tf, spec, df):
        if len(n) == 1:
            raise RuntimeError("boom")
        n.append(1)
        real_write(self, sym, tf, spec, df)

    monkeypatch.setattr(store_mod.TradeStore, "write", flaky)
    with pytest.raises(RuntimeError):
        search.build_trades(SYN_COINS[:1], specs=TINY_SPECS, store_dir=sd)
    d = sd / f"{SYN_COINS[0]}_{config.TIMEFRAMES[0]}"
    assert len(list(d.glob("*.pkl"))) == 1 and not (d / "_done").exists()
    monkeypatch.setattr(store_mod.TradeStore, "write", real_write)
    st = search.build_trades(SYN_COINS[:1], specs=TINY_SPECS, store_dir=sd)
    ref = search.build_trades(SYN_COINS[:1], specs=TINY_SPECS)
    for s in TINY_SPECS:
        pd.testing.assert_frame_equal(_sorted(ref[s]), _sorted(st[s]))


def test_store_parallel_build_equals_serial(synthetic, tmp_path):
    loaders = (_synthetic_1m, _synthetic_funding)       # top-level, so spawned workers can import
    ser = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=tmp_path / "s", loaders=loaders)
    par = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=tmp_path / "p", workers=2,
                              loaders=loaders)
    for s in TINY_SPECS:
        assert len(par[s]) > 0
        pd.testing.assert_frame_equal(_sorted(ser[s]), _sorted(par[s]))
    again = search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=tmp_path / "p", workers=2,
                                loaders=None)   # all cached: loaders unused
    assert len(again[TINY_SPECS[0]]) == len(par[TINY_SPECS[0]])


def _count_resolves(monkeypatch):
    calls, real = [], search.resolve_trades

    def spy(sc, m1, funding, spec, sym, tf):
        calls.append((sym, tf))
        return real(sc, m1, funding, spec, sym, tf)

    monkeypatch.setattr(search, "resolve_trades", spy)
    return calls


def test_store_unchanged_inputs_skip_but_changed_data_or_costs_rebuild(synthetic, tmp_path, monkeypatch):
    sd = tmp_path / "st"
    search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    calls = _count_resolves(monkeypatch)
    search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    assert calls == []                                     # same data, same costs: all cached
    # newer/shorter 1m data for one coin: only that coin's pairs rebuild
    monkeypatch.setattr(search.data, "load_1m", lambda s: _synthetic_1m(s).iloc[:-1]
                        if s == SYN_COINS[1] else _synthetic_1m(s))
    search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    assert {c[0] for c in calls} == {SYN_COINS[1]} and len(calls) == len(TINY_SPECS) * 2
    calls.clear()
    search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    assert calls == []
    monkeypatch.setattr(search.trades_mod, "SLIPPAGE", 0.0005)   # cost change: everything rebuilds
    search.build_trades(SYN_COINS, specs=TINY_SPECS, store_dir=sd)
    assert len(calls) == len(TINY_SPECS) * 4


def test_store_version_bump_rebuilds(synthetic, tmp_path, monkeypatch):
    sd = tmp_path / "st"
    search.build_trades(SYN_COINS[:1], specs=TINY_SPECS, store_dir=sd)
    calls = _count_resolves(monkeypatch)
    monkeypatch.setattr(store_mod, "STORE_VERSION", store_mod.STORE_VERSION + 1)
    search.build_trades(SYN_COINS[:1], specs=TINY_SPECS, store_dir=sd)
    assert len(calls) == len(TINY_SPECS) * 2
