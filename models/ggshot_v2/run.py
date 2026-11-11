"""CLI: python -m models.ggshot_v2.run {download,search,sanity}."""

import argparse
import logging

import pandas as pd

from . import data, search
from .config import COINS, START, TIMEFRAMES
from .detector import DetectorParams, apply_params, scan

SIGNALS_CSV = "tools/ggshot_research/signals.csv"
SANITY_TOLERANCE_BARS = 2


def sanity():
    """Share of channel calls (15 coins x 30m/1h) matched by a same-side detector signal within +-2 bars."""
    calls = pd.read_csv(SIGNALS_CSV)
    calls["ts"] = pd.to_datetime(calls["ts"], utc=True)
    calls = calls[calls.pair.isin(COINS) & calls.tf.isin(TIMEFRAMES)]
    tally = {tf: [0, 0] for tf in TIMEFRAMES}        # tf -> [considered, matched]
    for sym in COINS:
        sub = calls[calls.pair == sym]
        if sub.empty:
            continue
        m1 = data.load_1m(sym)
        bars_4h = data.resample(m1, "4h")
        for tf in TIMEFRAMES:
            rows = sub[sub.tf == tf]
            if rows.empty:
                continue
            bars = data.resample(m1, tf)
            dur = pd.Timedelta(minutes=data.TF_MINUTES[tf])
            sig = apply_params(scan(bars, bars_4h), DetectorParams())
            for side, label in ((1, "Long"), (-1, "Short")):
                times = pd.DatetimeIndex(sig.signal_time[sig.side == side])
                for ts in rows.ts[rows.side == label]:
                    # signal bar = last bar whose close (open + tf) <= post time
                    bar_open = (ts - dur).floor(f"{data.TF_MINUTES[tf]}min")
                    tally[tf][0] += 1
                    if len(times) and (abs(times - bar_open) <= SANITY_TOLERANCE_BARS * dur).any():
                        tally[tf][1] += 1
    n = sum(v[0] for v in tally.values())
    hit = sum(v[1] for v in tally.values())
    print(f"channel calls considered: {n}")
    print(f"matched (same side, within +-{SANITY_TOLERANCE_BARS} bars): {hit} ({hit / n:.1%})" if n else "no calls")
    for tf, (c, m) in tally.items():
        print(f"  {tf}: {m}/{c}" + (f" ({m / c:.1%})" if c else ""))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m models.ggshot_v2.run")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download", help="fetch 1m klines + funding for all coins")
    sub.add_parser("search", help="in-sample grid search, finalists, one out-of-sample run")
    sub.add_parser("sanity", help="sanity checks on the downloaded data and the pipeline")
    args = parser.parse_args(argv)

    if args.command == "download":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        data.download(COINS, START)
    elif args.command == "search":
        search.search()
    elif args.command == "sanity":
        sanity()


if __name__ == "__main__":
    main()
