# GG-Shot v2 backtest: results

Runs: in-sample search and finalists `reports/ggshot_v2/20261111_174825/` (11 Nov 2026); out-of-sample results `reports/ggshot_v2/20261111_230119_slotfix/` (the same three finalists re-run once after a portfolio-rule fix, see the note below). Spec: `docs/superpowers/specs/2026-11-11-ggshot-v2-design.md`.

**Note on the portfolio-rule fix.** The first run let a new trade take a slot in the same minute another trade exited. An exit is recorded in the minute its stop or target is hit, while a next-open entry fills at that minute's open, so for up to a minute a fourth trade (or a second trade on the same coin) could be open. The rule now treats a slot as taken through its exit minute: an exit in minute m frees the slot only for entries after m, and at equal timestamps entries are counted before exits. Only the out-of-sample run was repeated, for the same three finalists. The in-sample ranking and the finalist choice were made under the old convention and were deliberately not redone, to avoid a second look at 2025+ data. The results turn out to be sensitive to this one-minute convention, because the greedy 3-slot selection is path-dependent: one different acceptance changes which later trades fit, and only between about a third and three-quarters of each finalist's selected trades are the same under the two rules. Average R per selected trade, old rule → new rule:

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Out-of-sample | +0.079 (394) → +0.086 (406) | +0.157 (317) → +0.246 (308) | +0.163 (396) → +0.087 (374) |
| In-sample (for reference, not used to reselect) | +0.217 (762) → +0.132 (753) | +0.203 (526) → +0.060 (534) | +0.228 (801) → +0.094 (864) |

The in-sample drop for all three is what selection noise looks like: they were the best of 4,032 configurations under one convention, and a small perturbation pulls them back toward the average. Section 4's in-sample tables, and the in-sample claims about all 4,032 configurations (best win rate 38.6%, none reaching 40%), are under the old convention and were not recomputed.

## 1. Verdict

**It fails your bar.** No finalist reached a 40% win rate out-of-sample. The three finalists won 28.1%, 32.5% and 28.3% of trades from 2025 onward, all at a 3R target. In-sample (under the original slot convention), the best any of the 4,032 configurations managed was 38.6% (a 2R target, with a lower average profit per trade), and none reached 40%. At 3R a trade needs about 25% wins to break even before costs, so these sit a few points above break-even, not near 40%.

Gate by gate (out-of-sample, $20 risk; the $25 case is in section 5):

| Gate | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---|---|---|
| Win rate ≥ 40% | fail (28.1%) | fail (32.5%) | fail (28.3%) |
| Max drawdown < 10% | fail (13.7%) | pass (8.6%) | fail (10.1%) |
| Real 2025+ sequence reaches $5,500 before $4,700 | pass | pass | pass |
| Bootstrap pass rate ≥ 65% | pass (65.3%) | pass (90.4%) | fail (64.8%) |
| At least 100 trades, still profitable without the 5 best trades | pass | pass | pass |
| No coin above 30% of net profit | fail (54%) | pass (20%) | fail (78%) |
| **Overall** | **fail** | **fail** | **fail** |

Finalist 2 misses only the win-rate gate at $20 risk, and the win-rate gate is the bar you set, so it fails. The strategy was mildly profitable out-of-sample (+0.09R to +0.25R per trade net of all costs). Section 7 compares it with random bars from the breakout superset with a random side, using the same stop and target. Finalist 1 is no better than those random entries. Finalists 2 and 3 do better than all three random runs, but by margins of about 1.5 to 2 standard errors against the closest run, and finalist 2's controls are not like-for-like. These per-finalist averages also moved by up to 0.09R under a one-minute change to the slot rule (note above). The edge, if any, is small and nowhere near what the 40% win-rate bar needs.

## 2. What was tested

- **Signal.** A closed 30m or 1h candle that closes at its N-candle closing extreme in the trend direction (EMA20 vs EMA50), with RSI(14) beyond a level and volume above a multiple of its 20-candle average. Longs and shorts mirror each other.
- **Entry.** Either a market order at the next candle's open, or a pre-registered "confirm" variant: wait 5, 15 or 30 minutes after the close and enter only if price moves 0.25 or 0.5 ATR past the signal close in the signal direction.
- **Exit.** One stop, one target at 2R or 3R; no partial exits, no breakeven move. If stop and target fall inside the same candle, the stop counts.
- **Grid.** Detector: 4 lookbacks (15, 20, 25, 30) × 4 RSI levels (55, 60, 65, 70) × 3 volume multiples (1.0, 1.5, 2.0) = 48. Trade rules: 6 stops (swing, Supertrend, ATR × 1.5, 2, 3, 4) × 2 targets × 7 entries = 84. Total **4,032 configurations**, all ranked in-sample.
- **Costs.** Taker 0.05% on entry and stop, maker 0.02% on the target, 2 bps slippage on market orders, and Binance historical funding charged at every 8-hour mark a trade is open. The $20 (or $25) is the price distance to the stop, so a full loss is slightly more than that. All R, win-rate and dollar figures are net; a trade is a win only if its net P&L is positive.
- **Portfolio.** One $5,000 account shared by 30m and 1h, maximum 3 open trades, one per coin, 15 coins. Simultaneous signals: 1h before 30m, then fixed coin order. A slot is taken from the entry minute through the exit minute. One set of thresholds for all coins and both timeframes.
- **Challenge.** Equity reaches $5,500 before touching $4,700 (fixed floor). Also bootstrapped: the out-of-sample trade list was resampled 5,000 times, and the gate is at least 65% of runs reaching $5,500 first.
- **Selection discipline.** Ranking, filters and finalist choice used in-sample data (before 2025-01-01) only. Configurations needed at least 150 in-sample trades and were ranked by in-sample average net R. At most 3 finalists, each run out-of-sample once per portfolio-rule version; the only change afterwards was the slot-rule fix (see the note at the top), with the same finalists. Stage 2 (extra filters: higher-timeframe trend, over-extended run, hour of day, volatility regime) was tried because no stage-1 finalist passed all in-sample gates (and no configuration reached 40% in-sample); it tried the filters on the top 5 and **kept 0 variants**, since none improved on its base in-sample.

## 3. Data coverage and sanity check

- 15 coins, Binance USDT-M perpetual 1-minute candles and funding rates. Monthly archives from 2021-01 through 2026-10 for every coin, plus the current month through the REST API. Every coin has the same set of files.
- In-sample: before 2025-01-01. Out-of-sample: 2025-01-01 onward.
- **Sanity check against the channel.** Of 49 channel calls on these coins and 30m/1h charts, the detector at its default settings flagged **42 (85.7%)** within ±2 candles on the same side (1h: 9 of 11; 30m: 33 of 38). So the detector finds the same kind of setup the channel posts. That does not show it picks the same ones, which is where the earlier research located the channel's edge.

## 4. In-sample results and finalist selection

Top 10 of the 4,032 ranked configurations (in-sample, before 2025; all were eligible), as ranked under the old same-minute slot convention (see the note at the top; not recomputed). "Lookback / RSI / Vol" is the detector setting. Max drawdown is at $20 risk. All use a 3R target.

| Rank | Lookback / RSI / Vol | Stop | Entry | Trades | Win | Avg R | PF | Max DD | Challenge |
|---:|---|---|---|---:|---:|---:|---:|---:|:--:|
| 1 | 15 / 55 / 1.5 | ATR × 4 | confirm 30 min, 0.25 ATR | 801 | 31.6% | +0.228 | 1.32 | 8.5% | no |
| 2 | 30 / 65 / 1.5 | swing | confirm 30 min, 0.5 ATR | 385 | 31.7% | +0.228 | 1.32 | 5.9% | yes |
| 3 | 20 / 55 / 1.0 | ATR × 4 | next open | 762 | 31.4% | +0.217 | 1.31 | 5.0% | yes |
| 4 | 30 / 70 / 1.0 | swing | confirm 15 min, 0.5 ATR | 384 | 31.3% | +0.208 | 1.29 | 8.8% | yes |
| 5 | 20 / 55 / 1.5 | swing | confirm 15 min, 0.5 ATR | 566 | 31.3% | +0.204 | 1.29 | 8.8% | yes |
| 6 | 15 / 70 / 1.5 | swing | next open | 526 | 31.0% | +0.203 | 1.28 | 8.2% | yes |
| 7 | 20 / 70 / 1.5 | swing | next open | 526 | 31.0% | +0.203 | 1.28 | 8.2% | yes |
| 8 | 25 / 70 / 1.5 | swing | next open | 526 | 31.0% | +0.203 | 1.28 | 8.2% | yes |
| 9 | 30 / 70 / 1.5 | swing | next open | 526 | 31.0% | +0.203 | 1.28 | 8.2% | yes |
| 10 | 30 / 65 / 1.5 | swing | confirm 15 min, 0.25 ATR | 464 | 30.8% | +0.201 | 1.28 | 9.3% | yes |

Ranks 6 to 9 are the same trade set (the lookback made no difference at RSI 70 and volume 1.5).

Target comparison across all 4,032 configurations (in-sample): the best 3R configuration averaged +0.228R with a best win rate of 31.7%; the best 2R configuration averaged +0.124R with a best win rate of 38.6%. A 2R target wins more often but earns less per trade, and still does not reach 40%.

These are the best of 4,032 tries, so they are inflated by selection: with that many configurations, some will look good in-sample by chance.

**Finalists** (rule: best two next-open configurations plus the best confirm configuration; rank 7 to 9 duplicate rank 6, so rank 6 stands for them):

| Finalist | In-sample rank | Configuration |
|---|---:|---|
| 1 | 3 | lookback 20, RSI 55, volume 1.0, ATR × 4 stop, 3R, next open |
| 2 | 6 | lookback 15, RSI 70, volume 1.5, swing stop, 3R, next open |
| 3 | 1 | lookback 15, RSI 55, volume 1.5, ATR × 4 stop, 3R, confirm 30 min, 0.25 ATR |

## 5. Out-of-sample results (2025-01-01 onward, run once per rule)

Run `reports/ggshot_v2/20261111_230119_slotfix/`. Trade count, win rate, average R and profit factor do not depend on the risk amount; only dollars and drawdown do.

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Trades | 406 | 308 | 374 |
| Win rate | 28.1% | 32.5% | 28.3% |
| Average R (net) | +0.086 | +0.246 | +0.087 |
| Profit factor | 1.12 | 1.35 | 1.12 |

**$20 risk (main case)**

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Total P&L | +$699 | +$1,514 | +$651 |
| Max drawdown | 13.7% ✗ | 8.6% ✓ | 10.1% ✗ |
| Challenge, real sequence | ✓ 9 May 2025, after 90 trades | ✓ 27 Jan 2025, after 20 trades | ✓ 10 Oct 2025, after 211 trades |
| Bootstrap pass rate | 65.3% ✓ | 90.4% ✓ | 64.8% ✗ |
| Largest coin share of profit | 53.9% (ETH) ✗ | 19.8% (ETH) ✓ | 77.9% (BTC) ✗ |
| Win rate ≥ 40% | ✗ | ✗ | ✗ |
| At least 100 trades; profit without top 5 | ✓ ✓ | ✓ ✓ | ✓ ✓ |
| Peak total notional | $4,618 | $3,315 | $4,042 |
| **All gates** | **fail** | **fail** | **fail** |

**$25 risk (sensitivity)**

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Total P&L | +$874 | +$1,893 | +$814 |
| Max drawdown | 16.3% ✗ | 10.4% ✗ | 12.4% ✗ |
| Challenge, real sequence | ✓ 18 Jan 2025, after 19 trades | ✓ 20 Jan 2025, after 19 trades | ✓ 3 Feb 2025, after 43 trades |
| Bootstrap pass rate | 60.5% ✗ | 84.9% ✓ | 59.6% ✗ |
| Largest coin share of profit | 53.9% ✗ | 19.8% ✓ | 77.9% ✗ |
| Win rate ≥ 40% | ✗ | ✗ | ✗ |
| **All gates** | **fail** | **fail** | **fail** |

Note on the challenge: all six runs pass on the real sequence, four of them within 19 to 43 trades by early February 2025. A $500 gain before a $300 loss is a short race, so one favourable early run is enough. The bootstrap rate is the better guide to repeatability; finalist 1 clears it only just at $20 and finalist 3 misses it.

Caveats on these figures:

- **Max drawdown is on closed trades only.** With up to 3 trades open, each with its stop at risk, the intra-trade drawdown could be roughly 1 to 1.5 points worse than shown.
- **The bootstrap draws trades one at a time**, with no concurrency and no open-risk floor check. The real-sequence rule counts open stops against the $4,700 floor, so the bootstrap is more optimistic than that rule.
- **3 trades per finalist close as END** (still open at the last minute of data, closed at that minute's close).
- **A handful of in-sample trades exit after 2025-01-01** (3 per finalist): they are assigned to a period by decision time, not exit time.

## 6. Breakdowns (out-of-sample, $20 risk)

Outside BTC, ETH and SOL, each coin has only 1 to 37 trades per finalist, so individual coin results are mostly noise.

**By year**

| | 2025 | 2026 (to date) |
|---|---|---|
| Finalist 1 | 207 trades, 30.9%, +0.204R, +$847 | 199 trades, 25.1%, -0.037R, -$147 |
| Finalist 2 | 190 trades, 31.1%, +0.205R, +$778 | 118 trades, 34.7%, +0.312R, +$736 |
| Finalist 3 | 230 trades, 29.6%, +0.145R, +$669 | 144 trades, 26.4%, -0.006R, -$18 |

Finalists 1 and 3 made all their profit in 2025 and were flat to negative in 2026; finalist 2 held up in 2026.

**By side** (2025-26 was largely a falling market)

| | Longs | Shorts |
|---|---|---|
| Finalist 1 | 199 trades, 27.6%, +0.054R | 207 trades, 28.5%, +0.117R |
| Finalist 2 | 155 trades, 32.9%, +0.267R | 153 trades, 32.0%, +0.224R |
| Finalist 3 | 186 trades, 26.3%, +0.011R | 188 trades, 30.3%, +0.162R |

Finalist 2 is balanced between sides. Finalists 1 and 3 lean on shorts (finalist 3's longs were flat), which would fit a falling market but is not conclusive on these sample sizes.

**By timeframe**

| | 1h | 30m |
|---|---|---|
| Finalist 1 | 184 trades, 26.6%, +0.039R | 222 trades, 29.3%, +0.125R |
| Finalist 2 | 111 trades, 22.5%, -0.134R | 197 trades, 38.1%, +0.460R |
| Finalist 3 | 111 trades, 26.1%, +0.002R | 263 trades, 29.3%, +0.123R |

For all three finalists most of the profit comes from 30m; finalist 2's 1h trades lost money and finalist 3's were flat. Finalist 2's 30m trades won 38.1% on 197 trades, still below 40%.

**By coin** (trades, win rate, average R, total $)

| Coin | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---|---|---|
| BTC | 132, 28.8%, +0.09R, +$244 | 53, 30.2%, +0.15R, +$164 | 62, 37.1%, +0.41R, +$507 |
| ETH | 83, 31.3%, +0.23R, +$377 | 63, 31.7%, +0.24R, +$299 | 37, 37.8%, +0.48R, +$356 |
| SOL | 70, 28.6%, +0.12R, +$167 | 23, 39.1%, +0.51R, +$233 | 31, 35.5%, +0.39R, +$241 |
| BNB | 27, 25.9%, -0.00R, -$2 | 34, 20.6%, -0.23R, -$153 | 37, 29.7%, +0.15R, +$107 |
| XRP | 21, 42.9%, +0.69R, +$290 | 30, 36.7%, +0.44R, +$265 | 32, 28.1%, +0.10R, +$63 |
| DOGE | 9, 0.0%, -1.02R, -$184 | 6, 0.0%, -1.04R, -$124 | 11, 27.3%, -0.04R, -$9 |
| ADA | 8, 25.0%, -0.03R, -$5 | 22, 31.8%, +0.24R, +$106 | 19, 21.1%, -0.19R, -$72 |
| AVAX | 9, 0.0%, -1.03R, -$185 | 13, 38.5%, +0.51R, +$131 | 23, 30.4%, +0.19R, +$86 |
| LINK | 4, 0.0%, -1.04R, -$84 | 10, 60.0%, +1.36R, +$273 | 11, 27.3%, +0.06R, +$14 |
| DOT | 8, 37.5%, +0.47R, +$75 | 7, 42.9%, +0.38R, +$53 | 20, 20.0%, -0.32R, -$128 |
| LTC | 12, 41.7%, +0.64R, +$153 | 7, 28.6%, +0.11R, +$15 | 22, 18.2%, -0.31R, -$136 |
| NEAR | 8, 12.5%, -0.52R, -$83 | 11, 45.5%, +0.80R, +$175 | 19, 36.8%, +0.44R, +$169 |
| UNI | 8, 25.0%, -0.02R, -$4 | 7, 57.1%, +1.28R, +$179 | 13, 0.0%, -1.03R, -$267 |
| AAVE | 6, 16.7%, -0.35R, -$42 | 9, 22.2%, -0.38R, -$68 | 14, 14.3%, -0.46R, -$128 |
| FIL | 1, 0.0%, -1.01R, -$20 | 13, 23.1%, -0.13R, -$33 | 23, 17.4%, -0.33R, -$153 |

Concentration: finalist 1 made 54% of its net profit on ETH ($377 of $699), with XRP and BTC adding most of the rest while most other coins were flat or lost. Finalist 3 made 78% on BTC ($507 of $651). The same coin is good for one finalist and bad for another (AVAX, LINK, UNI, LTC), which points to noise rather than to coins that suit the signal.

## 7. Control test: is there a real edge?

To read the out-of-sample numbers fairly, each finalist's configuration (all 15 coins, 30m and 1h, new slot rule) was compared with two controls, using `tools/ggshot_research/control_test.py` (output in `tools/ggshot_research/control_results.txt`):

- **Flipped:** the same signal bars, same stop rule, target and entry rule, but the trade goes the opposite way.
- **Random:** the same number of bars per coin and timeframe, sampled at random from the breakout-scan superset, each with a random side, same stop rule, target and entry rule. Run with 3 random seeds.

"All" means every signal resolved as its own trade (heavily overlapping); "selected" means after the 3-slot, one-per-coin portfolio rules. Average R per trade, net (number of trades in brackets). The "actual, selected" rows match the tables above.

**Out-of-sample (2025+)**

| | Finalist 1 all | Finalist 1 selected | Finalist 2 all | Finalist 2 selected | Finalist 3 all | Finalist 3 selected |
|---|---:|---:|---:|---:|---:|---:|
| Actual signal | -0.003 (77,432) | +0.086 (406) | +0.049 (21,462) | +0.246 (308) | -0.002 (36,254) | +0.087 (374) |
| Flipped direction | -0.069 | -0.074 (314) | -0.174 | -0.203 (4,785) | -0.079 | -0.238 (257) |
| Random, seed 0 | -0.043 | +0.120 (293) | -0.102 | -0.077 (845) | -0.046 | -0.121 (312) |
| Random, seed 1 | -0.023 | -0.081 (375) | -0.121 | -0.061 (758) | -0.047 | -0.099 (413) |
| Random, seed 2 | -0.043 | -0.080 (350) | -0.106 | +0.001 (330) | -0.055 | -0.105 (373) |

**In-sample (before 2025)**

| | Finalist 1 all | Finalist 1 selected | Finalist 2 all | Finalist 2 selected | Finalist 3 all | Finalist 3 selected |
|---|---:|---:|---:|---:|---:|---:|
| Actual signal | +0.033 (159,397) | +0.132 (753) | +0.063 (45,243) | +0.060 (534) | +0.051 (76,489) | +0.094 (864) |
| Flipped direction | -0.073 | -0.083 (595) | -0.195 | -0.164 (9,409) | -0.080 | -0.190 (607) |
| Random, seed 0 | -0.017 | +0.015 (780) | -0.084 | +0.000 (1,985) | -0.023 | +0.022 (748) |
| Random, seed 1 | -0.026 | -0.014 (686) | -0.067 | +0.029 (830) | -0.030 | -0.039 (814) |
| Random, seed 2 | -0.026 | +0.039 (629) | -0.092 | -0.121 (1,695) | -0.021 | -0.050 (862) |

What it shows:

- **Across all signals, the actual direction beats random by a small, consistent margin**: about +0.02 to +0.08R per trade for finalists 1 and 3 across both periods, and the flipped direction does about as much worse. That points to a small directional tilt in the breakout signal, well short of what a 40% win rate at 3R would need.
- **After the portfolio rules, the picture is mixed and noisy.** Out-of-sample, finalist 1 (+0.086R) sits inside the range of its three random runs (-0.081 to +0.120R). Finalists 2 and 3 are above all three of their random runs, by about 0.25R and 0.2R. A selected-trade average over 300 to 400 trades has a standard error of about 0.09 to 0.11R. Against the closest random run the gaps are roughly 1.5 to 2 standard errors of the difference, and against the mean of the three runs about 2 to 2.5: suggestive, not conclusive with only three seeds. The three random seeds of finalist 1 alone span 0.2R, which shows how much the selected average moves by chance.
- **Finalist 2's controls are not like-for-like.** It uses a swing stop, and a flipped or random-side trade on a breakout bar has its swing level right next to price, so its stop is mostly widened to the 1.0 ATR minimum (checked on BTC 30m: 80% of flipped trades sit at 1.0 ATR, median 1.0 ATR, against a median of 4.2 ATR for the actual trades). Those controls therefore have tighter stops, higher costs per R and many more, shorter trades (the flipped set has over 4,700 selected trades against 308). Part of finalist 2's lead over its controls is this stop difference, not the entry.
- **The selected averages are fragile.** Changing the one-minute slot convention moved finalist 2 from +0.157R to +0.246R and finalist 3 from +0.163R to +0.087R out-of-sample, and the finalists' in-sample averages fell from +0.20 to +0.23R to +0.06 to +0.13R (note at the top). A result that moves this much under a one-minute bookkeeping change is not a stable estimate of edge.
- For the actual signal across all trades out-of-sample, longs averaged -0.091R (finalist 1), -0.033R (finalist 2) and -0.098R (finalist 3), and shorts +0.075R, +0.121R and +0.083R. 2025-26 favoured shorts, so the out-of-sample profit leans on the market direction.

Taken together: there is a small directional tilt, but the evidence for an edge large enough to matter is weak, and nothing here comes close to the 40% win-rate bar.

## 8. What it would take and next options

- **The 40% win-rate bar and a 3R target do not fit this signal.** Every top 3R configuration wins about 30%. A 2R target wins more often (best 38.6% in-sample, original slot convention) but earns less per trade, and no configuration reached 40%.
- **The channel's advantage appears to lie in which calls it picks**, not in the trigger (see `docs/research/ggshot-signals-analysis.md`). The detector overlaps 85.7% with the channel's calls but trades every fire, and the fires the channel did not call lost money on average in that research.
- **Further tuning needs fresh data.** The 2025+ period has now been used for three finalists (run once under each slot rule, with the finalists fixed in advance). Any new configuration chosen from these results would have to be tested on data nobody has looked at (for example several months of forward paper trading) to mean anything. Re-tuning against 2025+ would make it in-sample.
- **If the aim is the $5,500 challenge rather than the win-rate bar,** finalist 2 cleared the challenge, drawdown and bootstrap gates at $20 (not the drawdown gate at $25) and failed only on win rate. Finalists 1 and 3 also failed on drawdown and one-coin concentration, and finalist 3 on the bootstrap. That is a different goal from the bar you set, and finalist 2's figures moved a lot under a one-minute change to the slot rule (+0.157R to +0.246R per trade), so they are not a stable estimate, and its control comparison is not like-for-like (section 7). The weak 2026 results of finalists 1 and 3 also argue against relying on this.
- **Not tested here:** other timeframes or coins, partial exits and trailing stops (excluded by your rules), and tight stops: the fixed ATR stops start at 1.5 ATR, and swing and Supertrend stops closer than 1.0 ATR are widened to 1.0 ATR, so nothing tighter than 1.0 ATR was tested (earlier research showed tight stops do badly after these signals).
