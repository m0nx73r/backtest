"""Download Binance USDT-M futures klines around every GG-Shot call (300 bars before, 1199 after).
Falls back to spot klines if the futures symbol does not exist. One CSV per call id."""
import os, sys, time
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "call_candles")
os.makedirs(OUT, exist_ok=True)
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
URLS = {"futures": "https://fapi.binance.com/fapi/v1/klines", "spot": "https://api.binance.com/api/v3/klines"}
COLS = ["open_time", "open", "high", "low", "close", "volume"]

sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
status = []
s = requests.Session()
for _, r in sig.iterrows():
    path = os.path.join(OUT, f"{r.id}.csv")
    if os.path.exists(path):
        status.append((r.id, "cached")); continue
    m = TF_MIN.get(r.tf)
    if m is None:
        status.append((r.id, "bad_tf")); continue
    start = int((r.ts - pd.Timedelta(minutes=300 * m)).timestamp() * 1000)
    got = None
    for venue, url in URLS.items():
        resp = s.get(url, params={"symbol": r.pair, "interval": r.tf, "startTime": start, "limit": 1500}, timeout=20)
        if resp.status_code == 429 or resp.status_code == 418:
            time.sleep(60); resp = s.get(url, params={"symbol": r.pair, "interval": r.tf, "startTime": start, "limit": 1500}, timeout=20)
        if resp.status_code == 200 and resp.json():
            got = (venue, resp.json()); break
    if not got:
        status.append((r.id, "missing")); continue
    venue, rows = got
    df = pd.DataFrame([x[:6] for x in rows], columns=COLS)
    df["open_time"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    df[COLS[1:]] = df[COLS[1:]].astype(float)
    df.to_csv(path, index=False)
    status.append((r.id, venue))
    time.sleep(0.35)
st = pd.DataFrame(status, columns=["id", "venue"])
st.to_csv(os.path.join(HERE, "call_candles_status.csv"), index=False)
print(st.venue.value_counts().to_dict())
