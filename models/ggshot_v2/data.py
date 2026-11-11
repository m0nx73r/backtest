"""Binance USDT-M futures 1m klines and funding rates: download, cache, resample."""

import glob
import io
import logging
import os
import time
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

from models.ggshot_v2.config import DATA_DIR as _CFG_DATA_DIR, MIN_BAR_COVERAGE

log = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = _CFG_DATA_DIR if os.path.isabs(_CFG_DATA_DIR) else os.path.join(_ROOT, _CFG_DATA_DIR)

ARCHIVE = "https://data.binance.vision/data/futures/um/monthly"
API = "https://fapi.binance.com/fapi/v1"
PAUSE = 0.2          # seconds between HTTP calls
RETRIES = 5
TF_MINUTES = {"30m": 30, "1h": 60, "4h": 240}
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
FUNDING_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]
OHLCV = ["open", "high", "low", "close", "volume"]


# ----------------------------------------------------------------------- HTTP

def _get(url, params=None):
    """GET with retry/backoff on 429/418/5xx and network errors; 404 is returned as is."""
    delay = 1.0
    resp = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=60)
            if resp.status_code not in (429, 418) and resp.status_code < 500:
                return resp
        except requests.RequestException as exc:
            log.warning("GET %s failed: %s", url, exc)
        if attempt < RETRIES - 1:
            time.sleep(delay)
            delay *= 2
    return resp


def _pause():
    if PAUSE:
        time.sleep(PAUSE)


# ------------------------------------------------------------------- download

def _months(start, end):
    """(year, month) tuples from start's month to end's month inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _fetch_zip(url, dest):
    """Download one archive file unless it exists. Returns True when the file is present."""
    if os.path.exists(dest):
        return True
    _pause()
    resp = _get(url)
    if resp is None or resp.status_code == 404:
        log.warning("not available, skipped: %s", url)
        return False
    if resp.status_code != 200:
        log.warning("HTTP %s, skipped: %s", resp.status_code, url)
        return False
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(resp.content)
    os.replace(tmp, dest)
    return True


def _write_tail(df, dest, ok):
    """Atomically replace a tail file; keep the existing one if the fetch errored or was empty."""
    if not ok or (df.empty and os.path.exists(dest)):
        log.warning("tail fetch failed or empty, keeping existing %s", dest)
        return
    tmp = dest + ".part"
    df.to_csv(tmp, index=False)
    os.replace(tmp, dest)


def _tail_klines(symbol, since_ms, dest):
    rows, t, ok = [], since_ms, True
    while True:
        _pause()
        resp = _get(f"{API}/klines", {"symbol": symbol, "interval": "1m",
                                      "startTime": t, "limit": 1500})
        if resp is None or resp.status_code != 200:
            ok = False
            break
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        t = batch[-1][0] + 60_000
        if len(batch) < 1500:
            break
    _write_tail(pd.DataFrame([r[:12] for r in rows], columns=KLINE_COLS), dest, ok)


def _tail_funding(symbol, since_ms, dest):
    rows, t, ok = [], since_ms, True
    while True:
        _pause()
        resp = _get(f"{API}/fundingRate", {"symbol": symbol, "startTime": t, "limit": 1000})
        if resp is None or resp.status_code != 200:
            ok = False
            break
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        t = int(batch[-1]["fundingTime"]) + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame({"calc_time": [int(r["fundingTime"]) for r in rows],
                       "funding_interval_hours": 8,
                       "last_funding_rate": [float(r["fundingRate"]) for r in rows]},
                      columns=FUNDING_COLS)
    _write_tail(df, dest, ok)


def download(symbols, start):
    """Fetch monthly archives (klines + funding) for every symbol; REST fills the unarchived tail."""
    now = datetime.now(timezone.utc)
    first = pd.Timestamp(start, tz="UTC")
    last_full = pd.Timestamp(now.year, now.month, 1, tz="UTC") - pd.Timedelta(days=1)
    for sym in symbols:
        raw = os.path.join(DATA_DIR, "raw", sym)
        os.makedirs(raw, exist_ok=True)
        missing = []
        for y, m in _months(first, last_full):
            ym = f"{y}-{m:02d}"
            ok_k = _fetch_zip(f"{ARCHIVE}/klines/{sym}/1m/{sym}-1m-{ym}.zip",
                              os.path.join(raw, f"{sym}-1m-{ym}.zip"))
            _fetch_zip(f"{ARCHIVE}/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip",
                       os.path.join(raw, f"{sym}-fundingRate-{ym}.zip"))
            if not ok_k and (y, m) >= (last_full.year, last_full.month):
                missing.append((y, m))
        # REST tail: current month, plus last month when its archive is not published yet
        ty, tm = missing[0] if missing else (now.year, now.month)
        since = max(int(pd.Timestamp(ty, tm, 1, tz="UTC").timestamp() * 1000),
                    int(first.timestamp() * 1000))
        _tail_klines(sym, since, os.path.join(raw, "tail_1m.csv"))
        _tail_funding(sym, since, os.path.join(raw, "tail_funding.csv"))
        log.info("%s downloaded", sym)


# --------------------------------------------------------------------- parsing

def _read_text(path):
    if str(path).lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return z.read(z.namelist()[0]).decode("utf-8")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_table(path):
    """CSV (plain or zipped) with an optional header row -> string DataFrame without header."""
    text = _read_text(path)
    if not text.strip():
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(text), header=None, dtype=str)
    if not str(df.iloc[0, 0]).strip().lstrip("-").isdigit():     # header row present
        df = df.iloc[1:]
    return df.reset_index(drop=True)


def _read_kline_csv(path):
    """Parse one kline CSV/zip (header optional) -> OHLCV frame indexed by UTC open time."""
    df = _read_table(path)
    if df.empty:
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz="UTC", name="open_time"),
                            dtype=float)
    idx = pd.DatetimeIndex(pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms", utc=True)).as_unit("ns")
    out = df.iloc[:, 1:6].astype(float)
    out.columns = OHLCV
    out.index = pd.DatetimeIndex(idx, name="open_time")
    return out


def _read_funding_csv(path):
    df = _read_table(path)
    if df.empty:
        return pd.Series([], dtype=float, index=pd.DatetimeIndex([], tz="UTC", name="calc_time"))
    idx = pd.DatetimeIndex(pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms", utc=True)).as_unit("ns")
    s = df.iloc[:, 2].astype(float)
    s.index = pd.DatetimeIndex(idx, name="calc_time")
    return s


def _raw_files(symbol, pattern):
    return sorted(glob.glob(os.path.join(DATA_DIR, "raw", symbol, pattern)))


def load_1m(symbol):
    """All 1m bars for a symbol (sorted, de-duplicated), cached as .npz."""
    files = _raw_files(symbol, "*-1m-*.zip") + _raw_files(symbol, "tail_1m.csv")
    if not files:
        raise FileNotFoundError(f"no raw 1m data for {symbol} under {DATA_DIR}")
    cache = os.path.join(DATA_DIR, "cache", f"{symbol}_1m.npz")
    if os.path.exists(cache) and os.path.getmtime(cache) >= max(os.path.getmtime(f) for f in files):
        z = np.load(cache)
        idx = pd.DatetimeIndex(pd.to_datetime(z["ts"], unit="ms", utc=True).as_unit("ns"), name="open_time")
        return pd.DataFrame({c: z[c] for c in OHLCV}, index=idx)
    df = pd.concat([_read_kline_csv(f) for f in files])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    ts = df.index.as_unit("ms").asi8.astype("int64")                # ms since epoch
    np.savez(cache, ts=ts, **{c: df[c].to_numpy(float) for c in OHLCV})
    return df


def load_funding(symbol):
    """Funding rate history: UTC funding time -> rate."""
    files = _raw_files(symbol, "*-fundingRate-*.zip") + _raw_files(symbol, "tail_funding.csv")
    if not files:
        raise FileNotFoundError(f"no raw funding data for {symbol} under {DATA_DIR}")
    s = pd.concat([_read_funding_csv(f) for f in files])
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = "funding_rate"
    return s


# ------------------------------------------------------------------- resample

def resample(m1, tf):
    """1m -> `tf` bars (open-time index). Drops sparse bars and the trailing incomplete bar."""
    n = TF_MINUTES[tf]
    grp = m1.groupby(m1.index.floor(f"{n}min"))
    bars = grp.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                   close=("close", "last"), volume=("volume", "sum"))
    bars["_n"] = grp["close"].size()
    bars = bars[bars["_n"] >= MIN_BAR_COVERAGE * n]
    last_end = m1.index[-1] + pd.Timedelta(minutes=1)
    bars = bars[bars.index + pd.Timedelta(minutes=n) <= last_end]
    bars = bars.drop(columns="_n")
    bars.index.name = "open_time"
    return bars
