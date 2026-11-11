import sys, re, glob, html, os
import pandas as pd
src = sys.argv[1]
files = sorted(glob.glob(os.path.join(src, "messages*.html")), key=lambda f: int(re.search(r"messages(\d*)", f).group(1) or 1))
rows = []
for f in files:
    s = open(f, encoding="utf-8").read()
    for m in re.finditer(r'<div class="message default clearfix( joined)?" id="message(\d+)">(.*?)(?=<div class="message (?:default|service))', s, re.S):
        body = m.group(3)
        ts = re.search(r'class="pull_right date details" title="([^"]+)"', body)
        txt = re.search(r'<div class="text">(.*?)</div>', body, re.S)
        reply = re.search(r'GoToMessage\((\d+)\)', body)
        t = ""
        if txt:
            t = re.sub(r"<br\s*/?>", "\n", txt.group(1))
            t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        rows.append({
            "id": int(m.group(2)),
            "ts": pd.to_datetime(ts.group(1), format="%d.%m.%Y %H:%M:%S UTC%z").tz_convert("UTC") if ts else pd.NaT,
            "has_photo": "media_photo" in body, "reply_to": int(reply.group(1)) if reply else None,
            "text": t,
        })
df = pd.DataFrame(rows).sort_values("id")
df.to_csv("tg_messages.csv", index=False)
print(len(df), df.ts.min(), df.ts.max(), "photos", df.has_photo.sum(), "replies", df.reply_to.notna().sum())
print(df.groupby(df.ts.dt.year).size().to_dict())
