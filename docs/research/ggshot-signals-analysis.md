# GG-Shøt signal analysis

Research notes for a **v2 strategy that borrows ideas from the GG-Shøt indicator calls**.
Goal (decided 2026-11-11): build a *profitable* strategy inspired by these calls — not a
clone of the indicator.

Status: research in progress. §4–§5 are measured on exchange candles; §6 directions are untested.

---

## 0. Corrections after independent review (2026-11-11) — read first

An independent review (scratch work in `tools/ggshot_research/review/`) found errors that
change earlier sections. Verified and fixed:

1. **Zone edges swapped on 27 longs from 2026-05-26.** The newer call template lists a long's
   zone low→high, so the parser took the far edge as the entry. `parse_signals.py` now takes
   the near edge as max(zone) for longs / min for shorts, and also parses a lowercase "long"
   (506 calls now). Relisted symbols whose candles start long after the call are skipped,
   and limit entries that gap through are filled at the open.
   **Corrected §4.1 (1-minute timing, near-edge entry):** channel plan **−0.008R, PF 0.97**;
   100% at T1 −0.009R, PF 0.96; 100% at T4 −0.036R, PF 0.94. By timeframe: 1h +0.12R,
   15m +0.06R, 30m −0.02R, 5m −0.27R. **The calls are slightly losing, not break-even.**
   §4.2 claim matching is unchanged in substance (77% of claims reproduced until the original stop).
2. **§6.1 used a late entry.** `exit_spike.py` enters at the next call-timeframe bar open,
   a median ~22 min after the post. With 1-minute data from the post, a 1 ATR stop / 1R
   target wins ~62% (+0.12R), not ~50%. So "tight stops are clearly worse" and "direction is
   a coin flip" are artifacts of entering late; treat §6.1 as superseded.
3. **The trigger in §5 has no edge by itself.** §5 describes the calls, but the same
   conditions (20-bar closing extreme, EMA20/50, Supertrend(10,3), RSI ≥ 60 / ≤ 40,
   volume ≥ 1×, ≥ 1.5 ATR 10-bar move, 10-bar cooldown) fire on ~2.7% of bars — about 100×
   more often than the channel posts. On the windows around the calls (~17k fires,
   entry next open):

   | Fires | n | 1.5 ATR stop, 2R | win % |
   |---|---:|---:|---:|
   | the channel did **not** call | 17,150 | **−0.098R** | 33% |
   | the channel called (fire ≤ 3 bars before the call's signal bar) | 176 | +0.743R | 61% |

   Uncalled fires lose with every stop/target tried (−0.07 to −0.16R). No single filter on
   RSI, volume, run-up, ATR%, EMA distance or candle body separated winners out of sample.
   Caveat: the "called" label uses the channel's later decision, so it shows *that* the
   channel selects well, not *how*.
4. **Price move before the post.** Between the signal-bar close and the post, price has
   already moved a median **0.56 ATR** in the call's direction. Entering at the first
   1-minute open after the post with a 1.5 ATR stop / 2R target: all calls +0.10R (39% win,
   before slippage); by pre-post move bucket: ≤0 ATR −0.01R, 0–0.25 +0.13R, 0.25–0.5 +0.09R,
   0.5–1 +0.19R, >1 ATR 0.00R (`post_move_check.py`). The edge is **not** only in calls that
   already moved, so the channel's selection uses information we have not identified
   (hypotheses, unverified: other inputs, VIP flow, or reposting calls that started well).
   The reviewer found copying posts within a minute falls to ≈0 at 0.05% slippage per side.

**Bottom line:** the visible trigger can be detected, but on its own it does not make money;
the calls' edge comes from the channel's selection, which is not yet reproducible.

---

## 1. Source data

| Item | Value |
|---|---|
| Source | Telegram channel export (HTML), `ChatExport_2026-11-11` |
| Messages | 7,109 (Jan 2018 – Nov 2026) |
| Photos | 3,916 messages had a chart image; **images were not exported** |
| Structured indicator calls | **505** (2022 – 2026), 331 long / 174 short |
| Distinct coins | ~250 (mostly alts; BTC 24, ADA 13, TRB 12, SOL 11, …) |
| Other content | marketing posts, "targets done" replies, 39 `#Report` posts, a few hand-written BTC calls |

Calls per year: 2022: 78 · 2023: 127 · 2024: 98 · 2025: 117 · 2026: 86

Calls per timeframe / horizon label:

| Timeframe | Calls | Label | Median step | Median zone width | Median risk from near edge |
|---|---:|---|---:|---:|---:|
| 5m | 39 | Scalp | 0.60% | 1.32% | 2.00% |
| 15m | 53 | Short-Term | 1.50% | 2.68% | 4.24% |
| 30m | 312 | Mid-Term | 1.79% | 3.86% | 5.36% |
| 1h | 83 | Mid-Term | 2.00% | 4.63% | 6.20% |
| 4h | 19 | Long-Term | 6.33% | 8.40% | 15.53% |

### Call template

```
📩 #NEOUSDT 1h | Mid-Term
📉 Long Entry Zone: 6.403-6.016
🎯 - Strategy Accuracy:  91.84%
Last 5 signals: 88.89% / Last 10: 92.86% / Last 20: 91.67%
Target 1: 6.550   Target 2: 6.698   Target 3: 6.845   Target 4: 7.287
🧲Trend-Line: 6.016
❌Stop-Loss: 5.878
💡After reaching the first target you can put the rest of the position to breakeven
```

The first number in the entry zone is the edge **nearest the market** (top for longs,
bottom for shorts); the second is the far edge.

---

## 2. Level geometry (decoded)

All levels derive from three numbers: the **near edge** `E`, the **far edge** `F` of the
entry zone, and a distance **`S` ("step")**. With `d = +1` for longs, `−1` for shorts:

| Level | Formula | Holds for |
|---|---|---|
| Trend-Line | `= F` | 91.5% of calls |
| Target 1 | `E + 1·S·d` | (definition of S) |
| Target 2 | `E + 2·S·d` | median spacing ratio 1.000 |
| Target 3 | `E + 3·S·d` | median spacing ratio 1.000 |
| Target 4 | `E + 6·S·d` (T3 + 3S) | median ratio 3.00 |
| Stop-Loss | `F − 1·S·d` | median (F→SL)/S ≈ 1.0 |

Consistency check: measured from the **zone midpoint**, Target 1 is almost exactly 1R
(median 1.010, 10–90% range 0.97–1.03). So the indicator's own frame is
"enter at mid-zone, risk = half zone + S, T1 = 1R".

Open question: what sets `S` and the zone width. Hypothesis: `S` is a multiple of ATR on
the call's timeframe, and the zone runs from the current price to a trend line.
**Needs candle data to test.**

---

## 3. What the "90% accuracy" really means

Entering at the **near edge** (first fill of the zone):

| Measure | Median | 10% – 90% |
|---|---:|---:|
| Risk (near edge → SL) | 5.3% of price | 2.1% – 9.2% |
| Target 1 reward, in R | **0.31R** | 0.21R – 0.50R |
| Target 4 reward, in R | **1.83R** | 1.18R – 2.98R |

- T1 is about a third of the risk away, so it is hit very often — a high "accuracy"
  figure is expected from the geometry alone and says little about profitability.
- Reaching T4 still pays under 2R against a full stop.
- The channel mostly posts winners: of 39 `#Report` posts, only 1 mentions a stop.
  Self-reported accuracy and "profit at 10x/20x leverage" figures should be ignored.

---

## 4. Real outcomes (replayed on exchange candles)

Candles: Binance USDT-M futures klines for each call's coin and timeframe, 300 bars before
to ~1,200 bars after the post (502 futures, 2 spot, 1 missing → 504 calls replayed).

Rules: only bars opening after the post time are tradable; limit entry must fill within
48 bars; stop checked before targets inside a bar; no target credit on the fill bar;
fees maker 0.02% (entry, targets) / taker 0.05% (stops, time exits). R = entry → stop.

| Entry | Filled | Exit plan | Win % | Avg R | Total R | PF |
|---|---:|---|---:|---:|---:|---:|
| Near edge `E` | 407 / 504 | 100% at T1 | 72.5% | −0.03 | −12.6 | 0.89 |
| Near edge `E` | 407 / 504 | 25% at each T1–T4, stop → entry after T1 *(channel's advice)* | 72.2% | −0.03 | −13.6 | 0.88 |
| Near edge `E` | 407 / 504 | 100% at T4, no breakeven | 34.2% | −0.06 | −26.1 | 0.90 |
| Zone midpoint | 249 / 504 | 100% at T1 | 43.0% | −0.16 | −40.0 | 0.73 |
| Zone midpoint | 249 / 504 | scaled, as above | 43.0% | −0.18 | −43.9 | 0.70 |

- **T1 is reached before the stop on 72.5% of filled calls, not 90%+.** T2: 36%, T3: 24%, T4: 13%.
- **No exit plan is profitable after fees.** The best is roughly break-even (−0.03R per call).
- **19% of calls never fill at the near edge** within 48 bars: price runs away first.
- **Waiting for the zone midpoint is worse**: fewer fills, and the fills are the losers.
- By timeframe (scaled plan): 1h +0.04R and 4h +0.01R per call; **5m scalps −0.31R**.
- By year: 2024 and 2026 slightly positive, 2022, 2023 and 2025 negative. Longs −0.05R, shorts −0.01R.

### 4.1 Re-run with 1-minute candles (supersedes the table above)

The first replay only started at the next full candle after the post (up to 59 min late on
1h calls), so it missed fast moves right after posting. Re-run with Binance 1-minute
futures candles for the first 25 h after each post, then the call's own timeframe
(`fetch_call_1m.py`, `USE_1M=1`):

| Entry | Filled | Exit plan | Win % | Avg R | Total R | PF |
|---|---:|---|---:|---:|---:|---:|
| Near edge `E` | 416 / 504 | 100% at T1 | 75.5% | **+0.007** | +2.8 | 1.03 |
| Near edge `E` | 416 / 504 | channel plan (25% each, BE after T1) | 75.2% | **+0.003** | +1.2 | 1.01 |
| Near edge `E` | 416 / 504 | 100% at T4, no BE | 35.8% | −0.021 | −8.7 | 0.97 |
| Zone midpoint | 248 / 504 | channel plan | 43.5% | −0.158 | −39.2 | 0.73 |

By timeframe (channel plan): **1h +0.08R**, 30m +0.02R, 15m +0.01R, 4h +0.01R, **5m −0.31R**.
By year: 2024 +0.04R, 2026 +0.11R; 2022, 2023, 2025 negative.

**Verdict:** acting within minutes at the near edge, the calls are about **break-even after
fees** (PF ≈ 1.0). Only the 1h calls look mildly positive (70 calls — too few to trust).

### 4.2 Why the channel looks "very profitable"

Matched 425 calls that have a target claim in the channel's own replies / `#Report` posts
(`compare_claims.py`):

- Counting targets **until the original stop, ignoring the breakeven move**, the replay
  reproduces **76%** of the channel's claims (the rest are mostly fill/timing differences).
  So the claims are real *price touches*; the issue is how they are scored.
- A call counts as a win once T1 is touched. **52% of calls that touched T1 went on to hit
  the original stop before T4** — still scored as wins (channel-style accuracy here: 75.5%).
- Profits are quoted at **10×/20× leverage on the best target reached**, not net of the stop
  or of the calls that failed.
- Calls with no follow-up claim (79) average **−0.59R**; they are simply not reported.

## 5. What triggers a call (inferred)

Measured on the last bar **closed** before each post (499 calls):

| Property at the signal bar | Result |
|---|---|
| Post delay after bar close | median 6 min (10–90%: 1–27 min) |
| Near edge `E` equals the signal bar's close | 54% exactly; 72% equal one of the last 6 closes |
| Close is the highest (long) / lowest (short) **close of the last 20 bars** | 77% (50 bars: 69%) |
| Close breaks the prior 20-bar **high/low** | 51% |
| EMA20 vs EMA50 in the call's direction | **96%** |
| Supertrend (10–20, ×1–3) in the call's direction | 95–97% |
| Supertrend flipped within the last 3 bars | only 10–23% → not a flip signal |
| RSI(14) | longs median 69 (IQR 63–74); shorts median 32 (IQR 28–37) |
| Volume vs prior 20-bar average | median 1.6× (IQR 1.0–2.7×) |
| Move over the last 10 bars | median 2.4 ATR in the call's direction |
| Signal candle body | median 0.76 ATR, with the trend |
| Zone width `E→F` | median 3.95 × ATR(14) (IQR 3.0–5.1) |
| Step `S` | median 1.8 × ATR(14) (IQR 1.3–2.5), not a fixed multiple (CV 0.66) |
| Trend-Line `F` vs Supertrend(14, 3) line | median difference ≈ 0, but within 5% of the zone only 7% of the time |

**Reading:** a GG-Shøt call is a **trend-continuation momentum breakout**. It fires on a
bar that closes at a new 20-bar extreme, in an established trend (EMAs stacked, Supertrend
agreeing), with strong momentum (RSI ~69/31, 2.4 ATR run, above-average volume). The
entry edge is that bar's close; the trend line sits about 4 ATR behind, roughly where a
Supertrend(14, 3)-style trailing line is, but not exactly that formula.

## 6. Implications for a v2 strategy

- T1 (a 1.8-ATR continuation) comes before a ~6-ATR adverse move 72% of the time, but the
  stop is ~3× farther than T1, so wins are small and stops are big. (The exit spike in
  §6.1 shows that better exits don't rescue it: the trigger itself has no clear edge.)
- Entering at the breakout close and **buying the pullback to mid-zone are both
  unprofitable as published.** v2 needs a different risk structure, not just a filter.
- Coin selection (which of ~250 coins get published) is still unknown.

### 6.1 Exit spike (throwaway, `tools/ggshot_research/exit_spike.py`)

Entry: market at the open of the first bar after the post (what a follower can do), taker fee.
65 stop/exit combinations: stop = original SL, trend line, or 1/1.5/2/3 × ATR(14);
exit = fixed 1–3R target, ATR trailing stop (1.5/2/3 ATR), with/without breakeven at 1R;
plus the channel's own scaled plan. Variants ranked on 297 calls before 2025, then checked
on 202 calls from 2025 on.

| Variant | Avg R, before 2025 | Avg R, 2025+ | PF, 2025+ |
|---|---:|---:|---:|
| Channel plan (orig SL, 25% at T1–T4, BE after T1) | +0.032 | **+0.009** | 1.08 |
| 2 ATR stop, 3R target | +0.008 | −0.104 | 0.87 |
| 2 ATR stop, 3R target, BE at 1R | −0.005 | −0.041 | 0.92 |
| Orig SL, 2 ATR trailing stop | −0.013 | −0.050 | 0.63 |
| 1 ATR stop, 1R target | −0.150 | −0.173 | 0.71 |

- **Nothing beats the channel's own plan, and that plan is only break-even** out of sample.
- **Tighter stops are clearly worse** (1 ATR stops: −0.15 to −0.37R). After the signal bar,
  price usually pulls back first, so tight stops get hit.
- **Trailing exits don't help** — the trend rarely continues far enough to pay for them.
- **With a 1 ATR stop and 1R target, the win rate is 49–51%** before fees: at that
  horizon the call's direction is about a coin flip.

**Conclusion:** the GG-Shøt trigger (trend-continuation momentum breakout) shows **no
exploitable directional edge** on these 499 calls once fees are paid. Changing stops and
exits doesn't create one. A v2 can borrow the trend/momentum vocabulary, but its edge has
to come from somewhere else (different entry timing, a selection filter, or a different
market condition), and that needs its own test.

---

## 7. chartsgg.com (checked 2026-11-11)

chartsgg.com is the GG-Shøt team's charting site (TradingView-style). What it reveals:

| Finding | Source | Use for v2 |
|---|---|---|
| GG-Shøt is a set of **strategies, each tied to one coin + one timeframe** ("choosing a strategy opens its market and timeframe") | /indicators/gg-shot | Explains the per-coin/TF calls; a v2 can likewise tune per market |
| GG-Shøt is filed under **Trend**; related indicators listed: MA, EMA, SMMA, **Supertrend** | /indicators/gg-shot | Supports the guess that the "Trend-Line" is a Supertrend/ATR-style trailing line |
| Four **trading modes**: Standard, Advanced, Channel, Classic | /indicators | Different level rules per mode; may explain the ~9% of calls that break the geometry in §2 |
| Users are told to **"confirm entries with GG-Osc"** | chart indicator panel | Entry = trend signal + oscillator confirmation |
| **GG-Osc**: own oscillator, 0–100 pane, modes RSI, SDO, EOT, **Combined** (default); marks where it "turned long or short"; high/low zones = stretched moves | /indicators/gg-osc | Candidate entry filter: RSI-family turn out of an extreme zone |
| Charts use **Binance USDT-M perpetual** candles (`fapi.binance.com`) | network requests | Backtest on futures klines, not spot |
| Signals are computed **server-side**; signal and oscillator data endpoints return 403 without a subscription | network requests | Can't be read from the site |

Access: the logged-in account is on the **Free** plan. GG-Shøt marks need *@GGShot_Bot
Premium*; GG-Osc needs Charts Premium or a GG-Shot subscription. With the current account,
no historical signals or oscillator values can be pulled from the site, so the trigger
logic has to be inferred from the 505 Telegram calls plus candle data. I did not try to
work around the paywall.

"SDO" and "EOT" are not defined on the site. Likely candidates (unconfirmed):
SDO = a standard-deviation (z-score) oscillator; EOT = Ehlers-style oscillator
(e.g. "Even Better Sinewave"/"Ehlers Oscillator Trend").

---

## Reproduction

Scripts in `tools/ggshot_research/` (run from that folder; outputs are CSVs next to the scripts, gitignored):

- `parse_tg.py <export dir>` → `tg_messages.csv` (id, UTC timestamp, has_photo, reply_to, text)
- `parse_signals.py` → `signals.csv` (one row per structured call) + geometry stats
- `fetch_call_candles.py` → Binance futures klines per call (`call_candles/<id>.csv`)
- `simulate_calls.py` → `call_outcomes.csv` + outcome tables (§4)
- `trigger_probe.py` → `trigger_probe.csv` + trigger stats (§5)
- `fetch_call_1m.py` → 1-minute futures klines for 25 h after each post (`call_1m/<id>.csv`)
- `compare_claims.py` → replay vs the channel's own target claims (§4.2)
- `exit_spike.py` → throwaway stop/exit comparison (§6.1; uses call-TF candles only)
