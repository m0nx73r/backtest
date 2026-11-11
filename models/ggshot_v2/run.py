"""CLI: python -m models.ggshot_v2.run {download,search,sanity}."""

import argparse
import logging

from . import data, search
from .config import COINS, START


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
        print("sanity: implemented in Task 8", flush=True)


if __name__ == "__main__":
    main()
