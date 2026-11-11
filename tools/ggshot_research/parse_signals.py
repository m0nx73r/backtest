import sys, re, pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_csv("tg_messages.csv", parse_dates=["ts"]); df.text = df.text.fillna("")
sig = df[df.text.str.contains("Entry Zone:", regex=False)]
num = r"([\d.]+)"
rows = []
for _, m in sig.iterrows():
    t = m.text
    h = re.search(r"#(\w+?)\s+(\w+)\s*\|\s*([\w-]+)", t)
    side = re.search(r"(Long|Short) Entry Zone:\s*" + num + r"\s*-\s*" + num, t, re.I)
    tg = [float(x) for x in re.findall(r"Target \d:\s*" + num, t)]
    tl = re.search(r"Trend-Line:\s*" + num, t); sl = re.search(r"Stop-Loss:\s*" + num, t)
    acc = re.search(r"Strategy Accuracy:\s*" + num, t)
    if not (h and side and sl and len(tg) == 4): continue
    sd = side.group(1).capitalize(); a, b = float(side.group(2)), float(side.group(3))
    # near edge (z1) = the edge closer to market: top of the zone for longs, bottom for shorts.
    # The 2026-05+ template lists the zone low->high for longs, so order in the text is not reliable.
    near, far = (max(a, b), min(a, b)) if sd == "Long" else (min(a, b), max(a, b))
    rows.append(dict(id=m.id, ts=m.ts, pair=h.group(1), tf=h.group(2), term=h.group(3), side=sd,
        z1=near, z2=far, t1=tg[0], t2=tg[1], t3=tg[2], t4=tg[3],
        trend=float(tl.group(1)) if tl else np.nan, sl=float(sl.group(1)), acc=float(acc.group(1)) if acc else np.nan))
s = pd.DataFrame(rows)
s.to_csv("signals.csv", index=False)
d = np.where(s.side == "Long", 1, -1)
e = s.z1                       # first price in zone = nearest to market (top for long, bottom for short)
far = s.z2
step = (s.t1 - e) * d
s["step_pct"] = step / e * 100
s["zone_pct"] = (e - far).abs() / e * 100
s["t2_step"] = (s.t2 - s.t1) * d / step; s["t3_step"] = (s.t3 - s.t2) * d / step; s["t4_step"] = (s.t4 - s.t3) * d / step
s["trend_eq_far"] = np.isclose(s.trend, far, rtol=1e-4)
s["sl_from_far_pct"] = (far - s.sl) * d / e * 100
s["risk_e_pct"] = (e - s.sl) * d / e * 100
s["t1_R_from_e"] = step / ((e - s.sl) * d)
s["t4_R_from_e"] = (s.t4 - e) * d / ((e - s.sl) * d)
mid = (e + far) / 2
s["t1_R_from_mid"] = (s.t1 - mid) * d / ((mid - s.sl) * d)
print(len(s), "parsed;", s.side.value_counts().to_dict())
cols = ["step_pct","zone_pct","t2_step","t3_step","t4_step","sl_from_far_pct","risk_e_pct","t1_R_from_e","t4_R_from_e","t1_R_from_mid"]
print(s[cols].describe(percentiles=[.1,.5,.9]).round(3).T)
print("trendline == far edge of zone:", s.trend_eq_far.mean().round(3))
print("step/zone ratio:", (s.step_pct / s.zone_pct).describe(percentiles=[.1,.5,.9]).round(3).to_dict())
print("sl-from-far / zone ratio:", (s.sl_from_far_pct / s.zone_pct).describe(percentiles=[.1,.5,.9]).round(3).to_dict())
print(s.groupby("tf")[["step_pct","zone_pct","risk_e_pct"]].median().round(2))
