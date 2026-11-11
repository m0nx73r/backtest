# GG-Shot v2 backtest: results

Run: `reports/ggshot_v2/20261111_174825/` (11 Nov 2026). Spec: `docs/superpowers/specs/2026-11-11-ggshot-v2-design.md`.

## 1. Verdict

**It fails your bar.** No configuration reached a 40% win rate out-of-sample. The three finalists won 27.9%, 30.3% and 30.3% of trades from 2025 onward, all at a 3R target. In-sample, the best any of the 4,032 configurations managed was 38.6% (a 2R target, with a lower average profit per trade), and none reached 40%. At 3R a trade needs about 25% wins to break even before costs, so these sit a few points above break-even, not near 40%.

Gate by gate (out-of-sample, $20 risk; the $25 case is in section 5):

| Gate | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---|---|---|
| Win rate ≥ 40% | fail (27.9%) | fail (30.3%) | fail (30.3%) |
| Max drawdown < 10% | fail (12.9%) | pass (8.6%) | pass (6.9%) |
| Real 2025+ sequence reaches $5,500 before $4,700 | pass | pass | pass |
| Bootstrap pass rate ≥ 65% | fail (61.8%) | pass (80.3%) | pass (81.3%) |
| At least 100 trades, still profitable without the 5 best trades | pass | pass | pass |
| No coin above 30% of net profit | fail (70%) | pass (29%) | fail (38%) |
| **Overall** | **fail** | **fail** | **fail** |

Finalist 2 misses only the win-rate gate at $20 risk. The strategy was mildly profitable out-of-sample (+0.08R to +0.16R per trade net of all costs), but section 7 shows that for finalist 1 this is no better than entering at random with the same stop and target.

## 2. What was tested

- **Signal.** A closed 30m or 1h candle that closes at its N-candle closing extreme in the trend direction (EMA20 vs EMA50), with RSI(14) beyond a level and volume above a multiple of its 20-candle average. Longs and shorts mirror each other.
- **Entry.** Either a market order at the next candle's open, or a pre-registered "confirm" variant: wait 5, 15 or 30 minutes after the close and enter only if price moves 0.25 or 0.5 ATR past the signal close in the signal direction.
- **Exit.** One stop, one target at 2R or 3R; no partial exits, no breakeven move. If stop and target fall inside the same candle, the stop counts.
- **Grid.** Detector: 4 lookbacks (15, 20, 25, 30) × 4 RSI levels (55, 60, 65, 70) × 3 volume multiples (1.0, 1.5, 2.0) = 48. Trade rules: 6 stops (swing, Supertrend, ATR × 1.5, 2, 3, 4) × 2 targets × 7 entries = 84. Total **4,032 configurations**, all ranked in-sample.
- **Costs.** Taker 0.05% on entry and stop, maker 0.02% on the target, 2 bps slippage on market orders, and Binance historical funding charged at every 8-hour mark a trade is open. The $20 (or $25) is the price distance to the stop, so a full loss is slightly more than that. All R, win-rate and dollar figures are net; a trade is a win only if its net P&L is positive.
- **Portfolio.** One $5,000 account shared by 30m and 1h, maximum 3 open trades, one per coin, 15 coins. Simultaneous signals: 1h before 30m, then fixed coin order. One set of thresholds for all coins and both timeframes.
- **Challenge.** Equity reaches $5,500 before touching $4,700 (fixed floor). Also bootstrapped: the out-of-sample trade list was resampled 5,000 times, and the gate is at least 65% of runs reaching $5,500 first.
- **Selection discipline.** Ranking, filters and finalist choice used in-sample data (before 2025-01-01) only. Configurations needed at least 150 in-sample trades and were ranked by in-sample average net R. At most 3 finalists, each run out-of-sample once, with no changes afterwards. Stage 2 (extra filters: higher-timeframe trend, over-extended run, hour of day, volatility regime) was tried because no stage-1 configuration passed all in-sample gates; it tried the filters on the top 5 and **kept 0 variants**, since none improved on its base in-sample.

## 3. Data coverage and sanity check

- 15 coins, Binance USDT-M perpetual 1-minute candles and funding rates. Monthly archives from 2021-01 through 2026-10 for every coin, plus the current month through the REST API. Every coin has the same set of files.
- In-sample: before 2025-01-01. Out-of-sample: 2025-01-01 onward.
- **Sanity check against the channel.** Of 49 channel calls on these coins and 30m/1h charts, the detector at its default settings flagged **42 (85.7%)** within ±2 candles on the same side (1h: 9 of 11; 30m: 33 of 38). So the detector finds the same kind of setup the channel posts. That does not show it picks the same ones, which is where the earlier research located the channel's edge.

## 4. In-sample results and finalist selection

Top 10 of the 4,032 ranked configurations (in-sample, before 2025; all were eligible). "Lookback / RSI / Vol" is the detector setting. Max drawdown is at $20 risk. All use a 3R target.

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

## 5. Out-of-sample results (2025-01-01 onward, run once)

Trade count, win rate, average R and profit factor do not depend on the risk amount; only dollars and drawdown do.

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Trades | 394 | 317 | 396 |
| Win rate | 27.9% | 30.3% | 30.3% |
| Average R (net) | +0.079 | +0.157 | +0.163 |
| Profit factor | 1.11 | 1.22 | 1.22 |

**$20 risk (main case)**

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Total P&L | +$626 | +$998 | +$1,289 |
| Max drawdown | 12.9% ✗ | 8.6% ✓ | 6.9% ✓ |
| Challenge, real sequence | ✓ 11 Jul 2025, after 150 trades | ✓ 27 Jan 2025, after 20 trades | ✓ 27 Jan 2025, after 28 trades |
| Bootstrap pass rate | 61.8% ✗ | 80.3% ✓ | 81.3% ✓ |
| Largest coin share of profit | 69.9% (ETH) ✗ | 29.1% (XRP) ✓ | 38.0% (BTC) ✗ |
| Win rate ≥ 40% | ✗ | ✗ | ✗ |
| At least 100 trades; profit without top 5 | ✓ ✓ | ✓ ✓ | ✓ ✓ |
| Peak total notional | $4,476 | $5,031 | $4,628 |
| **All gates** | **fail** | **fail** | **fail** |

**$25 risk (sensitivity)**

| | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---:|---:|---:|
| Total P&L | +$782 | +$1,248 | +$1,612 |
| Max drawdown | 15.5% ✗ | 10.4% ✗ | 8.3% ✓ |
| Challenge, real sequence | ✓ 18 Jan 2025, after 19 trades | ✓ 20 Jan 2025, after 19 trades | ✓ 27 Jan 2025, after 27 trades |
| Bootstrap pass rate | 57.0% ✗ | 74.7% ✓ | 75.3% ✓ |
| Largest coin share of profit | 69.9% ✗ | 29.1% ✓ | 38.0% ✗ |
| Win rate ≥ 40% | ✗ | ✗ | ✗ |
| **All gates** | **fail** | **fail** | **fail** |

Note on the challenge: all six runs pass on the real sequence, and five of the six do so within 19 to 28 trades in January 2025. A $500 gain before a $300 loss is a short race, so one favourable early run is enough. The bootstrap rate is the better guide to repeatability, and finalist 1 does not clear it.

## 6. Breakdowns (out-of-sample, $20 risk)

Most coins have only 4 to 30 trades per finalist, so individual coin results are mostly noise.

**By year**

| | 2025 | 2026 (to date) |
|---|---|---|
| Finalist 1 | 237 trades, 29.1%, +0.130R, +$614 | 157 trades, 26.1%, +0.004R, +$12 |
| Finalist 2 | 190 trades, 31.1%, +0.205R, +$778 | 127 trades, 29.1%, +0.087R, +$220 |
| Finalist 3 | 236 trades, 32.2%, +0.250R, +$1,179 | 160 trades, 27.5%, +0.034R, +$110 |

All three weakened in 2026; finalist 1 was flat.

**By side** (2025-26 was largely a falling market)

| | Longs | Shorts |
|---|---|---|
| Finalist 1 | 197 trades, 27.9%, +0.065R | 197 trades, 27.9%, +0.094R |
| Finalist 2 | 161 trades, 30.4%, +0.168R | 156 trades, 30.1%, +0.147R |
| Finalist 3 | 200 trades, 28.0%, +0.074R | 196 trades, 32.7%, +0.254R |

Finalists 1 and 2 are balanced between sides. Only finalist 3 leans on shorts (+0.254R vs +0.074R), which would fit a falling market but is one configuration and not conclusive.

**By timeframe**

| | 1h | 30m |
|---|---|---|
| Finalist 1 | 176 trades, 29.0%, +0.132R | 218 trades, 27.1%, +0.037R |
| Finalist 2 | 123 trades, 26.8%, +0.018R | 194 trades, 32.5%, +0.246R |
| Finalist 3 | 115 trades, 25.2%, -0.038R | 281 trades, 32.4%, +0.245R |

For finalists 2 and 3 nearly all the profit comes from 30m (finalist 3's 1h trades lost money). Finalist 1 tilts the other way, so there is no consistent timeframe effect.

**By coin** (trades, win rate, average R, total $)

| Coin | Finalist 1 | Finalist 2 | Finalist 3 |
|---|---|---|---|
| BTC | 113, 26.5%, +0.00R, +$3 | 48, 27.1%, +0.02R, +$20 | 66, 36.4%, +0.37R, +$490 |
| ETH | 88, 31.8%, +0.25R, +$437 | 74, 27.0%, +0.05R, +$75 | 29, 41.4%, +0.62R, +$358 |
| SOL | 64, 32.8%, +0.29R, +$369 | 23, 39.1%, +0.51R, +$233 | 40, 32.5%, +0.27R, +$214 |
| BNB | 25, 20.0%, -0.25R, -$125 | 34, 23.5%, -0.18R, -$123 | 52, 30.8%, +0.18R, +$191 |
| XRP | 24, 37.5%, +0.48R, +$228 | 25, 40.0%, +0.58R, +$290 | 27, 37.0%, +0.46R, +$249 |
| DOGE | 11, 9.1%, -0.67R, -$147 | 11, 18.2%, -0.31R, -$67 | 13, 38.5%, +0.43R, +$111 |
| ADA | 8, 37.5%, +0.48R, +$76 | 23, 30.4%, +0.18R, +$83 | 28, 28.6%, +0.11R, +$62 |
| AVAX | 6, 0.0%, -1.03R, -$124 | 15, 40.0%, +0.57R, +$171 | 22, 18.2%, -0.31R, -$135 |
| LINK | 7, 0.0%, -1.04R, -$145 | 9, 44.4%, +0.75R, +$134 | 20, 20.0%, -0.23R, -$92 |
| DOT | 9, 33.3%, +0.31R, +$55 | 6, 16.7%, -0.36R, -$44 | 15, 26.7%, -0.08R, -$24 |
| LTC | 14, 21.4%, -0.19R, -$52 | 9, 33.3%, +0.29R, +$51 | 23, 21.7%, -0.17R, -$79 |
| NEAR | 4, 25.0%, -0.02R, -$1 | 10, 50.0%, +0.98R, +$197 | 10, 20.0%, -0.23R, -$46 |
| UNI | 6, 16.7%, -0.35R, -$42 | 5, 40.0%, +0.59R, +$59 | 19, 21.1%, -0.19R, -$71 |
| AAVE | 11, 36.4%, +0.43R, +$95 | 12, 25.0%, -0.21R, -$49 | 17, 35.3%, +0.38R, +$130 |
| FIL | 4, 25.0%, -0.02R, -$2 | 13, 23.1%, -0.12R, -$32 | 15, 20.0%, -0.23R, -$69 |

Concentration: finalist 1 made 70% of its net profit on ETH ($437 of $626), and SOL added another $369 while most other coins were flat or lost. Finalist 3 leans on BTC (38%). The same coin is good for one finalist and bad for another (BNB, DOGE, AVAX, LINK), which points to noise rather than to coins that suit the signal.

## 7. Control test: is there a real edge?

To read the out-of-sample numbers fairly, finalist 1's configuration (lookback 20, RSI 55, volume 1.0, ATR × 4 stop, 3R, next open, all 15 coins, 30m and 1h) was compared with two controls, using `.superpowers/sdd/2026-11-11-ggshot-v2/control.py` (output in `control-results.txt` in the same folder):

- **Flipped:** the same signal bars, same stop and target, but the trade goes the opposite way.
- **Random:** the same number of bars sampled at random from the signal-scan superset, with a random side, same stop and target.

"All" means every signal resolved as its own trade (heavily overlapping); "selected" means after the 3-slot, one-per-coin portfolio rules. Average R per trade, net (number of trades in brackets):

| | In-sample, all | In-sample, selected | Out-of-sample, all | Out-of-sample, selected |
|---|---:|---:|---:|---:|
| Actual signal | +0.033 (159,397) | +0.217 (762) | -0.003 (77,432) | +0.079 (394) |
| Flipped direction | -0.073 (159,397) | -0.094 (606) | -0.069 (77,432) | -0.059 (305) |
| Random entries | -0.022 (159,511) | +0.013 (738) | -0.026 (77,318) | +0.081 (336) |

What it shows:

- **Out-of-sample, the actual signal is no better than random entries once the portfolio rules apply** (+0.079R vs +0.081R on 394 and 336 trades; sampling noise is far larger than that gap). Across all signals the actual set sits at -0.003R against -0.026R for random, a small difference. The positive out-of-sample result therefore looks like it comes from the stop, target and portfolio structure in a market that rewarded these trades, not from picking better entries.
- The flipped direction loses (about -0.06 to -0.07R), so the signal's direction is not useless. A small directional tilt cannot be ruled out, but it is small.
- **In-sample, the actual selected trades (+0.217R) beat random (+0.013R) clearly, and that gap did not carry into 2025+.** Finalist 1 was the best of 4,032 configurations in-sample, so part of that in-sample gap is selection rather than signal.
- For the actual signal across all trades out-of-sample, longs averaged -0.013R and shorts +0.055R.
- This control was run on finalist 1 only; finalists 2 and 3 were not tested the same way.

Taken together, the evidence for a real, repeatable edge is weak.

## 8. What it would take and next options

- **The 40% win-rate bar and a 3R target do not fit this signal.** Every top 3R configuration wins about 30%. A 2R target wins more often (best 38.6% in-sample) but earns less per trade, and no configuration reached 40%.
- **The channel's advantage appears to lie in which calls it picks**, not in the trigger (see `docs/research/ggshot-signals-analysis.md`). The detector overlaps 85.7% with the channel's calls but trades every fire, and the fires the channel did not call lost money on average in that research.
- **Further tuning needs fresh data.** The 2025+ period has now been used once, for three finalists. Any new configuration chosen from these results would have to be tested on data nobody has looked at (for example several months of forward paper trading) to mean anything. Re-tuning against 2025+ would make it in-sample.
- **If the aim is the $5,500 challenge rather than the win-rate bar,** finalists 2 and 3 cleared the challenge, drawdown (at $20, and finalist 3 also at $25) and bootstrap gates. Finalist 2 failed only on win rate at $20; finalist 3 failed on win rate and one-coin concentration. That is a different goal from the bar you set, and the control test and the weaker 2026 results argue against relying on it.
- **Not tested here:** other timeframes or coins, partial exits and trailing stops (excluded by your rules), and stops tighter than 1.5 ATR (earlier research showed they do badly after these signals).
