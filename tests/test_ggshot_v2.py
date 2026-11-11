"""Tests for the ggshot_v2 backtest package (no network access)."""

import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from models.ggshot_v2 import config, data  # noqa: E402

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
