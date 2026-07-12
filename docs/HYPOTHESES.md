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
