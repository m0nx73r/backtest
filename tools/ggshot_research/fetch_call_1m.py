"""Download 1-minute Binance futures klines for the first 1,500 minutes (25h) after each call
is posted, so fills and target/stop order right after the post are resolved at minute level."""
import os, time
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "call_1m")
os.makedirs(OUT, exist_ok=True)
URLS = {"futures": "https://fapi.binance.com/fapi/v1/klines", "spot": "https://api.binance.com/api/v3/klines"}
COLS = ["open_time", "open", "high", "low", "close", "volume"]

sig = pd.read_csv(os.path.join(HERE, "signals.csv"), parse_dates=["ts"])
s = requests.Session()
stat = {}
for _, r in sig.iterrows():
    path = os.path.join(OUT, f"{r.id}.csv")
    if os.path.exists(path):
        stat["cached"] = stat.get("cached", 0) + 1; continue
    start = int(r.ts.floor("min").timestamp() * 1000)
    got = None
    for venue, url in URLS.items():
        for _ in range(2):
            resp = s.get(url, params={"symbol": r.pair, "interval": "1m", "startTime": start, "limit": 1500}, timeout=20)
            if resp.status_code in (418, 429):
                time.sleep(60); continue
            break
        if resp.status_code == 200 and resp.json():
            got = resp.json(); break
    if not got:
        stat["missing"] = stat.get("missing", 0) + 1; continue
    df = pd.DataFrame([x[:6] for x in got], columns=COLS)
    df["open_time"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    df[COLS[1:]] = df[COLS[1:]].astype(float)
    df.to_csv(path, index=False)
    stat[venue] = stat.get(venue, 0) + 1
    time.sleep(0.35)
print(stat)
