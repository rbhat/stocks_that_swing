# Vision

Build a daily-data swing-trading engine that finds and paper-trades **3–15 session moves** in
liquid US stocks using multi-timeframe technical setups — higher-timeframe trend and levels
choosing *where* to look, daily-timeframe triggers choosing *when* to act — with risk sized to
swing-scale volatility, validated by pre-registered studies against history, and proven by a
fast-accruing forward paper book. Paper only; real money never, unless explicitly authorized
much later.

**The core bet:** short-horizon edges in equities are real but small and conditional
(trend-conditioned mean reversion, post-earnings drift, volatility-compression breaks). They
were invisible to the parent project because it measured them with a long-hold yardstick. Sized
and judged at their own scale, they compound through turnover: many small resolutions per year
instead of a few large ones.

**Success looks like:**
- At least one setup family with out-of-sample, event-level expectancy **> 0 net of 2× assumed
  friction**, on n ≥ 100 events, stable across years (no single regime carrying it).
- A forward paper book whose realized expectancy sits inside its out-of-sample band after
  **≥ 30 closed trades and ≥ 3 months** — swing velocity makes this cheap; forward evidence is
  the arbiter, and here it arrives in months, not years.
- Median hold ≤ 15 sessions; every trade carries its setup, trigger, stop, target, and time
  stop at entry — nothing is a black box.
- Drawdown inside the charter cap; friction share of gross P&L tracked on every report.

**The honest kill criterion:** if no hypothesis family survives its pre-registered Phase-3
bars (HYPOTHESES.md) after H1–H3 and one exploratory round, the project records a well-earned
STOP. The parent taught us how to park; a new repo is not an excuse to forget.

**Principles:**
- **Swing-native geometry.** Risk is anchored to the instrument's own volatility (ATR) and
  structure, never to a fixed percent designed for multi-year holds. Expectancy after friction
  is the governing criterion — not a reward-to-risk floor (the parent's ≥2R floor is the
  single biggest thing that broke swing there).
- **No shared surface with the parent.** Code, data, decisions, and configuration are never
  copied wholesale from `stocks_that_move`. LESSONS §7 names a short list of infrastructure
  files (calendar, fetch, store, quality gate, atomic-write plumbing) ported near-verbatim
  because they're horizon-agnostic; everything that encodes a risk, sizing, stop, target, or
  exit *decision* is designed fresh from this charter. The parent's specific numbers and
  geometry (30% stops, Fibonacci extension targets, fixed-% position sizing, the ≥2R floor)
  are never carried over — not even by accident of copy-paste from a ported file. Only
  LESSONS.md crosses the boundary as prior, never as design.
- **Edge before ops.** No dashboard, no alerts, no cloud VM until a study survives its gates
  and the forward book exists. The parent built world-class operations around an unproven
  edge; this project inverts the order.
- **Evidence discipline inherited whole** (LESSONS §5): pre-registration before any script,
  immutable OOS wall, append-only decision ledger, event-level judging on a wide roster,
  independent review before promotions, distributions over lucky paths.
- **Friction is first-class.** Swing turns over ~5–10× a long-hold book; every verdict is also
  run at 2× assumed costs, and a family that dies at 2× is reported as fragile.
- **Multi-timeframe, small and readable.** A handful of setups a human can narrate, each with
  a stated mechanism (who is on the wrong side and why they pay us). No indicator soup, no ML.

---

## Charter rules — RATIFIED 2026-07-11 (see decisions.md)

Capital & sizing:
- $100,000 simulated starting capital. Paper trading only.
- Per-trade risk: **0.75% of equity** (position size = risk budget ÷ stop distance).
- Per-position notional cap 15%; max **8 concurrent positions**; max 80% of equity deployed.
- Long only, permanently (ratified 2026-07-11: short side is off the table for this
  project, not merely phase-gated).

Stops & exits:
- Every position has a hard stop at entry: ATR-anchored (~2×ATR14) or structure-anchored
  (below the pullback low / gap base), study-determined; stop distance sanity-bounded to
  ≤ 12% of entry. Never widened. Never average down.
- **Time stop: 15 sessions, hard** (user constraint, 2026-07-11 — swing trades resolve in 2–3
  weeks or they are wrong).
- Targets are study-determined (structure: prior swing high / measured move / mean touch; or
  ATR multiples). **No hard R:R floor** — with right-sized stops the parent's tiny-win-vs-
  huge-stop pathology cannot occur, and mean-reversion families legitimately run high win
  rate at ~1:1. Planned R:R is reported on every trade and every study.

Entries & catalysts:
- No new entries within **2 sessions before** a scheduled earnings date; holding through
  earnings is allowed — no pre-event forced exits (user constraint, 2026-07-11). The
  earnings-drift family (H2) enters *after* the event by design and is embargo-compatible.

Universe & data:
- Liquid US common stocks/ETFs: price ≥ $5, average dollar volume ≥ $20M; roster ~150–250
  names + SPY/QQQ anchors; survivorship caveat stated on every artifact (the feed returns
  survivors — forward paper is the survivorship-free arbiter).
- Data hard rules inherited verbatim from the parent: local parquet cache is the source of
  truth; atomic writes (temp + fsync + replace); validate-before-write quality gate;
  split- and dividend-adjusted total-return basis, never mixed; incomplete bars never cached;
  jobs idempotent and resumable with ETA.
- **OOS wall: 2025-07-01, immutable.** Nothing fits on or past it. (H3's entry families
  partially consumed 2025+ in the parent — caveat carried in HYPOTHESES.)

Process:
- decisions.md append-only, newest first; every study pre-registered (bars locked before the
  script exists); PROCEED/PARK/STOP verdicts; independent review for promotions, risk-rule
  changes, and method changes; long-running scripts resumable with elapsed/ETA.
- trades.jsonl append-only when the forward book exists; alerts (if ever) are trade events
  only.
