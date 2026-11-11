# GG-Shøt-style v2 strategy — design

Date: 2026-11-11 · Status: draft for approval

## Intent

Build our own version of the GG-Shøt setup so we can **catch these calls ourselves** instead
of waiting for the Telegram channel, and trade them with simple, fixed risk to pass a
$5,000 trading challenge. First a **backtest** that proves (or disproves) it; a **live
scanner** comes later and is out of scope here.

Background research: `docs/research/ggshot-signals-analysis.md`. Key facts it established:

- A GG-Shøt call is a **trend-continuation momentum breakout**: the signal candle closes at
  a 20-candle closing extreme, in the direction of the trend (EMA20 vs EMA50 agrees 96%),
  with strong momentum (RSI(14) median 69 for longs / 32 for shorts, ~2.4 ATR run over the
  last 10 candles) and above-average volume (median 1.6× the 20-candle average).
- Traded as published, the channel's calls are about **break-even after fees**. Fixed 2R/3R
  targets on those calls won only ~27–35% of the time. So **copying the trigger is not
  enough**: v2 has to select better setups to reach the bar below. Failing to reach it is a
  legitimate outcome of this work and must be reported plainly.

### Reality check (added after the independent review)

Research §0: on ~17,000 historical trigger fires the channel did **not** call, the same
trigger **loses** (−0.10R at a 1.5 ATR stop / 2R, 33% wins). Only the fires the channel
picked make money, and we have not found how it picks. **The expected result of this
backtest is that the base strategy fails the bar.** It is still the real test (continuous
history on our 15 coins, which the review did not cover). To give it a fair chance, one
extra pre-registered variant is added below: **post-close confirmation**.

## Goals

1. A detector that finds GG-Shøt-style setups on closed candles, written so the future live
   scanner can reuse it unchanged.
2. A portfolio backtest over the universe below with the exact risk rules below.
3. A clear verdict against the acceptance bar, with in-sample and out-of-sample results kept
   separate.

## Acceptance bar (decided by the user)

| Measure | Bar |
|---|---|
| Win rate | **40–60%** |
| Reward : risk | **1:2 or 1:3** (single target) |
| Max drawdown | **under 10%** |
| Challenge | equity reaches **$5,500** before touching **$4,700** (fixed floor, not trailing) |

No time limit and no daily loss limit.

## Decided rules (user)

| Area | Rule |
|---|---|
| Account | $5,000 start |
| Risk per trade | **$20–25** fixed dollar risk; position size = risk ÷ stop distance |
| Exits | **one stop, one target** at 2R or 3R. No partial exits, no TP1–TP4, no breakeven move |
| Concurrency | **max 3 open trades, max one per coin** |
| Markets | Binance **USDT-M perpetual futures**: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT, LTC, NEAR, UNI, AAVE, FIL |
| Timeframes | **30m and 1h**. No 5m |
| Direction | long and short |
| Order | backtest first; live scanner later |

## My calls (check these)

- **Data period:** 2021-01-01 to the latest closed candle. **In-sample: before 2025-01-01.
  Out-of-sample: 2025-01-01 onward.** Every rule, threshold and option is chosen on
  in-sample data only; out-of-sample is run once per finalist and reported as-is.
- **Signal timing:** decide at the close of the signal candle; enter with a **market order
  at the next candle's open** (taker fee + 2 bps slippage). Only closed candles may be used.
- **Fees:** taker 0.05% on entry and stop; maker 0.02% on the take-profit (resting limit).
  Matches `FEE_TAKER` / `FEE_MAKER` in `core/config.py`.
- **Intrabar order:** if stop and target are both inside one candle, count the **stop**.
- **Starting detection rule** (from the research; thresholds tuned in-sample within the
  ranges given):
  - long: close = highest close of the last N candles (N in 15–30, start 20); EMA20 > EMA50;
    RSI(14) ≥ 60 (range 55–70); volume ≥ 1.0× 20-candle average (range 1.0–2.0).
  - short: mirror image (lowest close, EMA20 < EMA50, RSI ≤ 40, same volume rule).
  - The same coin and timeframe cannot signal again while a trade on that coin is open.
- **Stop placement candidates** (pick one in-sample): (a) beyond the most recent swing
  low/high, (b) k × ATR(14) from entry with k in 1.5–4, (c) a Supertrend(14, 3)-style
  trailing line at entry, used as a fixed stop. Research showed **tight stops (~1 ATR) do
  badly** after these signals, so stops under 1.5 ATR are not tried.
- **Target:** test 2R and 3R; report both.
- **Risk amount:** run with **$20** as the main case (15 full losses from start to floor)
  and $25 as a sensitivity check.
- **Simultaneous signals:** if more signals fire on the same candle than free slots, take
  them in a fixed coin-list order (deterministic, no peeking at outcomes).
- **Leverage/margin:** assume enough leverage is available (up to 10×) that position size is
  never margin-limited; report the peak total notional so this can be checked.
- **Challenge pass rate:** besides the single historical sequence, bootstrap-resample the
  out-of-sample trade list (≥ 5,000 runs) and report the share of runs that reach $5,500
  before $4,700. Proposed gate: **≥ 65%** (same threshold the repo already uses for its
  Monte Carlo check).
- **Post-close confirmation variant (pre-registered).** After a signal candle closes, wait up
  to **N minutes** (N in {5, 15, 30}); enter only if price trades at least **X × ATR(14)**
  beyond the signal close in the signal's direction (X in {0.25, 0.5}); enter at that
  moment (market, taker + slippage); otherwise skip. Same single stop / single target rules,
  stop measured from the actual entry. Needs 1-minute futures candles only for the window
  after each signal. X and N are chosen in-sample only; this variant counts as one of the
  3 finalists.
- **Filters to try only if the base rule misses the bar:** higher-timeframe trend agreement
  (4h EMA), skipping signals after an over-extended run (e.g. > 3 ATR in 10 candles),
  session/hour, ATR-percentile regime. Each one is judged in-sample and kept only if it
  helps there; out-of-sample is not used for selection.

## Verdict and selection rules (my calls, from the builder check)

- **One portfolio.** 30m and 1h trade in the same $5,000 account and share the 3 slots and
  the one-per-coin rule. When both timeframes signal on the same candle close, 1h goes
  before 30m, then coin-list order.
- **One set of thresholds for all coins and both timeframes.** No per-coin or per-timeframe
  tuning (too much overfitting for the data size).
- **Selection:** grid search on in-sample only. Rank configurations by **in-sample average
  net R per trade**, among those with ≥ 150 in-sample trades. At most **3 finalists** go to
  out-of-sample, each run once; no further changes after that.
- **The verdict is judged on out-of-sample results, for one configuration meeting all of
  these at once:** win rate ≥ 40% at its chosen target (2R or 3R — either is acceptable; 60%
  is not a ceiling), max drawdown < 10%, the real 2025+ sequence reaches $5,500 before
  $4,700, bootstrap pass rate ≥ 65%, and the robustness checks below.
- **Robustness:** ≥ 100 out-of-sample trades; still net-profitable with the 5 best trades
  removed; no single coin contributes more than 30% of net profit.
- **Costs:** the $20 is the stop distance in price (position size = $20 ÷ stop distance);
  fees, slippage and **funding** are charged on top, so a full loss is slightly more than
  $20. Funding uses Binance's historical funding rates for each 8-hour mark a trade is open
  through. All R, win-rate and P&L figures are **net** of every cost; a trade counts as a
  win only if its net P&L is positive.

## Non-goals

- The live scanner, Telegram alerts, order execution.
- Reproducing GG-Shøt's calls exactly, their TP1–TP4 levels, or their zone/trend-line maths.
- Partial exits, breakeven moves, trailing exits.
- Coins outside the list, 5m/15m/4h charts.

## Anti-goals (would make this a failure even if it "works")

- Any look-ahead: using a candle before it closes, or higher-timeframe data before it closes.
- Choosing thresholds by looking at 2025+ results.
- Results reported without fees, or a win rate quoted without the matching R:R.
- A pass that depends on one or two lucky trades or one coin.

## Constraints

- Reuse existing repo pieces where they fit: fee/slippage helpers in `core/costs.py`,
  config style in `core/config.py`, the look-ahead test pattern in
  `tests/test_backtest_correctness.py`.
- Futures candles must come from Binance USDT-M (`fapi`), not spot. The existing
  `tools/fetch_candles.py` uses spot via ccxt; extend it or add a futures option.
- Cached data stays out of git (`*.csv` is already ignored).

## Deliverables

1. Detector module (pure function: closed candles in → signals out), shared with the future
   live scanner.
2. Portfolio backtest runner with CLI options for risk amount, R target, stop method, and
   in-sample / out-of-sample period.
3. Tests: (a) look-ahead — each trade must be reproducible from data cut at its decision
   time; (b) fee and position-size maths; (c) concurrency limits (≤ 3 open, ≤ 1 per coin).
4. A results report: per-run trades CSV; summary of win rate, avg R, PF, max drawdown,
   challenge pass/fail on the real sequence, bootstrap pass rate, breakdown by coin,
   timeframe, side and year; in-sample and out-of-sample side by side.
5. A short sanity check: how many of the channel's own calls on these 15 coins × 30m/1h
   the detector also flags within ±2 candles (expect partial overlap; it is a check, not a
   target).

## Left to the builder

Module layout and names, data caching format, CLI design, how thresholds are searched
(grid size within the ranges above), report formatting.
