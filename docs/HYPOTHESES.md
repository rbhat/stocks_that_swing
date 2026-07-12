# Hypotheses — what to try, and why believe any of it

Ranked setup families for Phase 3. Each entry: the setup, the external evidence, the internal
priors carried from the parent project, a study sketch, and its failure modes. Bars shape at
the bottom applies to all.

## §0 Evidence calibration — read before believing anything below

The user's thesis — swing trading on multi-timeframe technicals is profitable — has genuine
support, but the honest version is conditional:

- **Published edges decay.** Across 97 published return anomalies, returns run ~26% lower
  out-of-sample and ~58% lower post-publication ([McLean & Pontiff](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623)).
  Assume any effect below is half its published size before costs.
- **The best-documented swing-horizon effects are conditional, not standalone.** Raw one-month
  reversal is largely a low-turnover-stock effect; high-turnover stocks actually *continue*
  over one month, and that short-term momentum survives transaction costs in the largest,
  most liquid names ([Medhat & Schmeling, Short-term Momentum](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3150525);
  [Alpha Architect summary](https://alphaarchitect.com/short-term-momentum/)). Conditioning is
  everything — which is exactly the multi-timeframe claim.
- **PEAD is real, persistent, and shrinking.** Quarterly hedge returns fell from ~5–6% in the
  1970s–80s to ~2–3% or lower in the 2010s, but five decades of study have not killed it
  ([review](https://www.sciencedirect.com/science/article/pii/S2214635020303750);
  [overview](https://en.wikipedia.org/wiki/Post%E2%80%93earnings-announcement_drift)). Weakest
  in mega-caps, strongest where attention is limited.
- **Practitioner mean-reversion (Connors RSI(2)-style) has 25+ years of documented backtests**
  with high win rates and 3–7 day holds, still reported viable in the 2020s with regime
  filters ([QuantifiedStrategies](https://www.quantifiedstrategies.com/rsi-2-strategy/),
  [StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2)) —
  but this is exactly the literature most exposed to publication decay and survivorship in
  vendor backtests. Treat as hypothesis source, never as proof.
- **Our own bar is therefore:** replicate on our data, our frictions (both cost arms), our
  OOS wall — or it doesn't exist for us. Daily bars also mean no intraday timing: every fill
  is next-session-open with slippage, which handicaps fast setups honestly.

Internal priors that say short-horizon signal exists in our own data (parent, 2026-07): every
entry family carried positive raw forward returns at 5/10/21 sessions (~+0.5%/+0.9%/+1.6%);
the avwap-252-above condition was price-predictive at every horizon tested; and the 10-bar
capped book was absolutely profitable on the virgin 2025+ tape (+27.5%, MAR 1.21, n=138) —
it only lost the *relative* duel against long-hold on a bull tape. Details: LESSONS §3.

---

## H1 — Trend-conditioned pullback (the multi-timeframe core; highest prior)

**Setup.** Higher timeframe says *own the name*: weekly uptrend (price above a rising 20/40-
week MA, or weekly higher-highs/higher-lows structure, or above avwap-252 — the in-house
validated condition). Daily timeframe says *it's briefly on sale*: pullback trigger fires —
RSI(2) < 10, or 3–5 consecutive down closes, or a tag/undercut of the 20-day MA, or an N-day
low. Entry on first strength (close back above prior day's high, or limit at the level). Exit
at the mean (10/20-day MA touch), prior swing high, or ~2×ATR — whichever the study crowns —
plus the 15-session time stop. Stop below the pullback low or 2×ATR.

**Why believe it.** This is short-term reversal *conditioned on medium-term momentum* — buying
short-term losers among long-term winners, which improves both raw legs (reversal literature:
[Jegadeesh 1990/Lehmann 1990 lineage](https://therobusttrader.com/short-term-reversal-effect-in-stocks/);
conditioning evidence per Medhat–Schmeling above; practitioner canon per Connors). In-house:
the parent's one long-horizon trend-filter test (bos_bullish × vol_squeeze) lifted event
expectancy enough to pass gate v2 — trend context demonstrably improves entry quality on our
own data. And the parent's crisis-alpha fold map showed fast exits winning stress years —
a pullback book with time stops inherits that defensive posture.

**Study sketch.** Grid is small and pre-registered, not swept: {3 trend conditions} × {3
pullback triggers} × {2 entry modes} × {3 exits}. Two-layer read (raw h=5/10/15 first).
Slices: year, era (pre/post-2015), regime (SPY above/below 200d), symbol-liquidity tercile.
**Failure modes:** it's all beta-dip-buying on a bull tape (regime slice must catch this);
entry fills on next-open give back the bounce (measure fill-lag cost explicitly); low-turnover
conditioning (per Medhat–Schmeling, reversal lives in low-turnover names — check a
dollar-volume interaction).

## H2 — Earnings-reaction drift (PEAD, price-proxy version)

**Setup.** After a report, use the first post-report session's price reaction as the surprise
proxy (gap % + close-vs-open + volume expansion — no fundamental data needed). Long the top
reaction decile: enter day-2 open or on the first 1–3 session pullback that holds; hold 5–15
sessions; ATR stop; time stop.

**Why believe it.** The most persistent anomaly in the literature (§0); the drift horizon
(days-to-weeks) matches our hold window exactly; price-reaction versions of the sort are
standard and robust. In-house: the parent already auto-fetches earnings dates
(`cache/catalysts/earnings.json` machinery) — infra exists; and the user's standing catalyst
rule (embargo before, hold-through allowed) is fully compatible since H2 enters *after* the
event. ~150–250 names × ~4 reports/yr ≈ 600–1,000 events/yr — statistical power is excellent.

**Study sketch.** Reaction-decile sort → forward returns h=1..15 (layer a) → exit-simmed
entries (layer b) on top-decile events; entry-mode A/B (day-2 vs pullback). Slices: year,
market-cap/liquidity tercile, reaction sign (report both tails; we trade long only).
**Failure modes:** yfinance earnings-date quality (parent found it workable; verify
coverage/accuracy on the roster first — a coverage report is part of the prereg); decay
concentrated in large caps (expect the edge in the smaller half of the roster); gap fills
eating the entry (the pullback entry-mode exists for this).

## H3 — Re-geometried breakout/squeeze (the parent's families, honestly re-tested)

**Setup.** The parent's detectors verbatim — vol_squeeze, consolidation_breakout,
sweep_reclaim, and the avwap-252 × vol_squeeze seed — but managed swing-native: ATR/structure
stop, structure target (measured move off the base), 15-session time stop.

**Why believe it.** These entries carry real short-horizon raw returns (parent layer-a). Both
parent parks tested them with *long-hold geometry plus a time cap* — the entry×exit confound
was never truly broken (LESSONS §2). The avwap seed book passed every bar in both parent
gate runs (recorded as post-hoc cross-check — a genuine prior, not proof). This is the honest
re-test the parent couldn't run inside its hard rules.

**Study sketch.** Same harness as H1; detectors ported verbatim, zero re-tuning. **Name the
primary cell in the prereg before looking** (the seed was looked at twice in the parent — this
time it must be chosen blind or declared as the known-prior cell it is).
**Caveats:** 2025+ OOS is *partially consumed* for these entries (parent swing studies ran
them there under time-cap exits) — verdicts state this; forward paper is the clean arbiter.
Lower prior than H1/H2: two parks, even confounded ones, are information.

## H4 — Exploratory bin (only if H1–H3 leave budget)

- **Turnover-conditioned short-term momentum:** high-turnover recent winners continue ~1
  month (Medhat–Schmeling) — matches our horizon, documented to survive costs in liquid
  names. Needs a turnover proxy (dollar-volume vs own history; shares outstanding not in the
  cache).
- **Gap continuation:** volume-confirmed breakaway gaps in uptrends, 1–5 session follow-
  through. Daily bars handicap this most — accept that or drop it.
- **Turn-of-month / seasonality:** overlay filter only, never a standalone entry.

## H5 — Short side (charter-gated; not a Phase-3 family)

Mean-reversion and breakdown setups mirror naturally, and the parent's fold map says fast
exits earn their keep in bear tapes — a long-only swing book is structurally bull-skewed
(parent named this bias explicitly). Parked until the Phase-5 book survives; requires a
charter amendment (VISION), never a silent addition.

## H6 — Additional entry setups (user-proposed 2026-07-11; open more trades, not gate fewer)

Four candidate setups the user raised. **Framing (user, explicit): these are trade-*openers*,
not filters** — they add ways into a position, they do not restrict the H1–H3 families. So
each is judged as its own event family under the same bars (§ bars shape) and the same §0
skepticism; none is allowed to loosen an existing family's rules. Two are uptrend
*continuation* (H6a/H6b, cousins of H1/H3/H4-gap); two are long *reversal off a downtrend*
(H6c/H6d) — a direction the project has never carried, so **lowest prior and highest
overfitting risk** of anything here: they are pattern-recognition-heavy, structurally rare
(small n ⇒ expect PARK-on-adequacy, not PROCEED), and drawn from practitioner canon (FVG/ICT,
Wyckoff) with thin academic support. They earn a look, not belief. Daily-bar honesty applies
throughout: no intraday timing, every fill next-session-open with slippage — which handicaps
every one of these.

**H6a — FVG break-and-retest in an uptrend.** *Setup:* in a confirmed uptrend (H1's HTF
condition), price leaves an unfilled fair-value gap — a 3-bar imbalance where bar-1 high < bar-3
low; when price later trades back down into a *key* FVG (one sitting at/under an HTF level or
the origin of the impulse) and holds, enter on the reclaim. *Mechanism:* the gap marks
where demand overwhelmed supply and left resting unfilled orders; the retest is where trapped
sellers and breakout buyers transact — we're paid by those who faded the impulse. *Operational
must-defines (prereg):* programmatic FVG detection, "key" = proximity to an HTF level/avwap,
"holds" = close back above the gap top within N sessions. *Failure modes:* gaps fill and keep
going (needs the hold confirmation, which costs the first move on a next-open fill); on daily
bars an FVG is common ⇒ over-triggers, so "key" must be strict or it's noise. Overlaps H1
(both are pullback-in-uptrend) — check whether it adds events H1 doesn't already catch, else
it's a relabel.

**H6b — Gap-up through resistance, buy the fib-discount pullback.** *Setup:* in an uptrend,
price gaps up and closes above a well-defined resistance (prior swing high / range top); wait
for a retracement into the *discount* zone of the breakout leg (~0.5–0.786 fib, i.e. the lower
half of the impulse) that holds above the broken level, then enter. *Mechanism:* the broken
resistance flips to support (old sellers now underwater defend break-even); buying the discount
half of the leg instead of chasing the gap is a better price for the same continuation thesis.
*Operational (prereg):* define the impulse leg (breakout bar to local high), the fib zone,
"holds above broken level" as the invalidation, and the gap-size band (breakaway vs runaway).
*Failure modes:* a deep-enough discount retrace often *is* a failed breakout — the stop must
sit just under the broken level and the time stop enforced; gap partially fills before the
zone, giving a worse entry than modeled. Cousin of H4-gap and H1 (buy-the-dip after a level
break).

**H6c — Island-bottom reversal.** *Setup:* after a downtrend, an exhaustion gap down, a brief
basing range, then a gap up that leaves the base isolated between two gaps (an "island"). Treat
the island top / gap-up bar as the trigger; research the entry (day-2 open vs reclaim of the
island high). *Mechanism:* the two gaps strand the late shorts and capitulation sellers on the
island — their covering fuels the reversal. *Operational (prereg):* gap definitions both sides,
max base width, min prior-downtrend depth; **name the entry rule blind before looking.**
*Failure modes:* genuinely rare on daily bars ⇒ n likely below the adequacy floor (PARK-on-
adequacy is the expected honest outcome, not a fail); island patterns are easy to see in
hindsight and hard to define crisply — resist tuning the definition to the winners.

**H6d — Wyckoff accumulation → break/retest (reversal off a downtrend).** *Setup:* after a
sustained downtrend, price stops trending and consolidates in a range (accumulation); watch for
a false breakdown that reclaims (spring), then a break *up* out of the range, then a pullback/
retest of the range top that holds — enter the retest. *Mechanism:* the spring runs stops
below the range and transfers supply to stronger hands; the breakout-retest is where the
doubters who sold the range give up — classic Wyckoff, stated plainly. *Operational (prereg):*
full Wyckoff schematics are subjective — reduce to a **mechanical proxy**: range detection
(volatility contraction + horizontal boundaries) → optional false-breakdown-reclaim flag →
breakout close above range top → retest-holds entry. Backtest the proxy, not the drawing.
*Failure modes:* the most discretionary setup here (highest researcher-degrees-of-freedom —
prereg the proxy exactly); "downtrend then range then up" is survivorship-flavored (we only see
the ranges that resolved up); retest may never come (miss) or fail (stop under range top).

**Study handling.** H6a/H6b run on the H1/H3 harness (trend condition + trigger + entry mode +
exit), detectors added, zero re-tuning. H6c/H6d need new reversal detectors and a
*downtrend* HTF condition — a small new module, unit-tested like `risk.py`. All four obey the
two-layer read (raw h=5/10/15 first) and the § bars. Priority: **below H1–H3, at/under H4** —
Phase-3 budget permitting; H6c/H6d only if H6a/H6b or H4 show the exploratory round is worth
extending.

**Stretch — confluence across configs (not "one config wins").** The user's point: on a given
name/date, several of these configs (and H1–H3) may fire together; the goal is not to crown a
single config but to find where independent setups *agree* on an entry zone — a confluence
region — and test whether agreement itself predicts better expectancy than any config alone.
Method sketch: log every config's trigger events with timestamps and levels; cluster
co-located events (same symbol, entries within k sessions / overlapping price zones); compare
expectancy of confluence clusters vs singletons. **Hazard, stated up front:** more configs = more
ways to manufacture a false positive (multiple comparisons). This is deferred to the Phase-4
portfolio layer *after* individual families have passed their own blind bars — confluence is a
combination study over survivors, never a fishing license to test all configs at once. Prereg
the clustering rule and the comparison before running it.

---

## Bars shape (pre-registered per study; numbers locked in each prereg, these are the shape)

- Layer (a) raw forward returns positive at the traded horizon — an entry that only wins
  after exit-sim is an exit artifact.
- Layer (b) event-level OOS expectancy > 0 **net of 2× friction**, n ≥ 100 OOS events
  (adequacy floor: below-n ⇒ PARK-on-adequacy, never STOP).
- Year-by-year stability: ≥ 60% of judgeable years positive with a ±(noise-band) neutral zone
  — near-zero years vote for nobody (parent method lesson).
- No single year > ~40% of total edge; regime slice (SPY 200d) reported, bull-only
  concentration flagged.
- Cost sensitivity: verdict also computed at 2× costs; survives = robust, dies = fragile
  (stated in the verdict).
- Verdicts: PROCEED (→ Phase 4) / PARK (recorded, revisitable on new evidence) / STOP
  (mechanism refuted). All three are wins over not knowing.
