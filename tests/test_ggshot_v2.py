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
