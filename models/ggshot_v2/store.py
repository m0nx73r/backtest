"""Disk-backed, resumable store of resolved trades per (coin, timeframe, TradeSpec).

Layout: ``root/<SYMBOL>_<tf>/<spec_key>.pkl`` plus a ``_done`` marker written only after every
spec file of that (coin, tf) exists. ``TradeStore`` is a read-only mapping TradeSpec -> DataFrame
that loads one spec at a time (only the most recently loaded spec is cached).
"""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

TIME_COLUMNS = ["signal_time", "decision_time", "entry_time", "exit_time"]
DONE = "_done"
# Bump by hand whenever scan / resolve_trades / detector logic changes: cached trades from an
# older version are then rebuilt. (Data identity and cost constants are fingerprinted automatically.)
STORE_VERSION = 1


def spec_key(spec):
    """Short, stable, filesystem-safe, unique-per-spec file stem.

    Numeric fields are normalised (float / int) so equal specs, e.g. TradeSpec("atr", 2, 2) and
    TradeSpec("atr", 2.0, 2.0), map to the same file.
    """
    return (f"{spec.stop_method}-{float(spec.stop_k)!r}_t{float(spec.target_r)!r}_{spec.entry}_"
            f"{int(spec.confirm_minutes)}_{float(spec.confirm_atr)!r}")


def empty_frame(columns):
    df = pd.DataFrame(columns=columns)
    for c in TIME_COLUMNS:
        if c in df.columns:
            df[c] = pd.Series(dtype="datetime64[ns, UTC]")
    return df


class TradeStore(Mapping):
    def __init__(self, root, specs, pairs, columns, period=None):
        self.root = Path(root)
        self._specs = list(specs)
        self.pairs = list(pairs)                  # [(symbol, tf), ...] belonging to this build
        self.columns = list(columns)
        self.period = period
        self._cache = (None, None)
        self._tmp = None                          # keeps a temporary root alive while in use

    # ---- writing
    def pair_dir(self, sym, tf):
        return self.root / f"{sym}_{tf}"

    def _stamp(self, fingerprint):
        return repr((self.period, STORE_VERSION, fingerprint))

    def is_done(self, sym, tf, fingerprint=None):
        d = self.pair_dir(sym, tf)
        marker = d / DONE
        if not marker.is_file() or marker.read_text() != self._stamp(fingerprint):
            return False
        return all((d / f"{spec_key(s)}.pkl").is_file() for s in self._specs)

    def write(self, sym, tf, spec, df):
        d = self.pair_dir(sym, tf)
        d.mkdir(parents=True, exist_ok=True)
        final = d / f"{spec_key(spec)}.pkl"
        part = final.with_name(final.name + ".part")
        df.to_pickle(part)
        os.replace(part, final)

    def begin(self, sym, tf):
        """Invalidate a (coin, tf) before (re)writing it."""
        d = self.pair_dir(sym, tf)
        if (d / DONE).exists():
            (d / DONE).unlink()

    def finish(self, sym, tf, fingerprint=None):
        marker = self.pair_dir(sym, tf) / DONE
        part = marker.with_name(DONE + ".part")
        part.write_text(self._stamp(fingerprint))
        os.replace(part, marker)

    # ---- reading (Mapping)
    def __getitem__(self, spec):
        if spec not in self._specs:
            raise KeyError(spec)
        if self._cache[0] == spec:
            return self._cache[1]
        frames = []
        for sym, tf in self.pairs:
            f = self.pair_dir(sym, tf) / f"{spec_key(spec)}.pkl"
            if f.is_file():
                df = pd.read_pickle(f)
                if len(df):
                    frames.append(df)
        out = (pd.concat(frames, ignore_index=True) if frames else empty_frame(self.columns))
        self._cache = (spec, out)
        return out

    def __iter__(self):
        return iter(self._specs)

    def __len__(self):
        return len(self._specs)

    def __contains__(self, spec):
        return spec in self._specs


def temp_root():
    tmp = tempfile.TemporaryDirectory(prefix="ggshot_v2_trades_")
    return tmp
