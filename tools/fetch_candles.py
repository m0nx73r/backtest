"""
Download historical OHLCV candles into the cache the backtests read:

    data/ohlcv/<BASE>_<QUOTE>/<timeframe>.csv
    columns: timestamp (bar OPEN time, UTC ISO-8601), open, high, low, close, volume

The still-forming last bar is dropped, so every row is a closed candle.

Examples (run from the repo root):
    python -m tools.fetch_candles                                  # config SYMBOLS, all TFs, DAYS_BACK+35
    python -m tools.fetch_candles --symbol BTC/USDT --tf 5m 1h 1d --days 400
    python -m tools.fetch_candles --symbol HYPE/USDT --tf 4h 15m --exchange okx
"""

import argparse
import os
import sys
import time

import ccxt
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.config import SYMBOLS, DATA_DIR, DAYS_BACK  # noqa: E402

DEFAULT_TFS = ["5m", "15m", "1h", "4h", "1d"]


def fetch_history(exchange, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    step_ms = exchange.parse_timeframe(timeframe) * 1000
    now_ms = exchange.milliseconds()
    since = now_ms - days * 86_400_000
    rows = []
    while since < now_ms:
        for attempt in range(5):
            try:
                batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
                break
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
                print(f"      retry {attempt + 1} after {type(e).__name__}")
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + step_ms
        if len(batch) < 1000:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df["timestamp"] + step_ms <= now_ms]          # closed candles only
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="Download OHLCV history into data/ohlcv/ for the backtests.")
    ap.add_argument("--symbol", nargs="+", default=SYMBOLS, help="e.g. BTC/USDT ETH/USDT")
    ap.add_argument("--tf", nargs="+", default=DEFAULT_TFS, help="timeframes, e.g. 5m 1h 1d")
    ap.add_argument("--days", type=int, default=DAYS_BACK + 35,
                    help="days of history (default: DAYS_BACK + 35 days of indicator warm-up)")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--out", default=DATA_DIR)
    args = ap.parse_args()

    exchange = getattr(ccxt, args.exchange)({"enableRateLimit": True})
    for sym in args.symbol:
        out_dir = os.path.join(args.out, sym.replace("/", "_"))
        os.makedirs(out_dir, exist_ok=True)
        for tf in args.tf:
            df = fetch_history(exchange, sym, tf, args.days)
            path = os.path.join(out_dir, f"{tf}.csv")
            df.to_csv(path, index=False)
            span = f"{df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}" if len(df) else "no data"
            print(f"  {sym:<10} {tf:>4}: {len(df):>7,} bars  {span}  -> {path}")


if __name__ == "__main__":
    main()
