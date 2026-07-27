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
- At least one setup family with **positive out-of-sample net profit after friction** on
  n ≥ 100 closed events. Every entry must offer **planned reward:risk > 1.5R**, and every
  initial stop must risk **< 25% of entry** (the charter's existing ≤ 12% stop bound is
  stricter). These are entry-time geometry bars; realized winners are reported as a
  distribution, not forced to exceed 1.5R after the fact.
- A forward paper book whose realized net return sits inside the matched-trade-count
  out-of-sample net-return band after
  **≥ 30 closed trades and ≥ 3 months** — swing velocity makes this cheap; forward evidence is
  the arbiter, and here it arrives in months, not years.
- Median hold ≤ 15 sessions; every trade carries its setup, trigger, stop, target, and time
  stop at entry — nothing is a black box.
- Drawdown inside the charter cap — **40% max peak-to-trough on net portfolio equity**
  (amended 2026-07-26); friction share of gross P&L tracked on every report. A portfolio
  backtest only counts as a real read at **≥ 10% average deployed** over its window
  (amended 2026-07-26) — a book that sits in cash proves nothing.

**The honest kill criterion:** if no hypothesis family survives its pre-registered Phase-3
bars (HYPOTHESES.md) after H1–H3 and one exploratory round, the project records a well-earned
STOP.

**Principles:**
- **Swing-native geometry.** Risk is anchored to the instrument's own volatility (ATR) and
  structure, never to a fixed percent designed for multi-year holds. The >1.5R planned
  reward:risk bar is a prospective entry-quality constraint; net profit after friction is
  still the outcome that governs. The bar must not be met by widening stops, extending the
  15-session hold, or relabeling old studies.
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

***Agent behavior***
Common: You're a technical-analysis trader with 20 years of experience, and a strong senior AI/ML engineer who architects and builds the simplest thing that works. No anti-patterns, no shortcuts, no forcing design or code, and never change the underlying strategy or education. Test what you build and audit it against these goals. Be concise and to the point, don't overexplain, go deeper when I ask.
Tell implementation subagents to give upto top 3 common errors and lets this to the coding rules to avoid. Add to coding_rules.md and point to it for agent runs. Keep it bullet point, clear and concise. Dont add explanation, history, reasoning or anything else to it.
Always use ruff --fix, not bare ruff. 
Use .scratch/ folder to create and execute temporary files and scripts. DO NOT ASK PERMISSIONS IN THIS REPO FOR BASH COMMANDS - YOU ARE AUTHORIZED.

Claude: Top level agent will think, deisgn, plan, architect and close the loop. Top level agent will use Opus 5.0 subagent to orchestrate, coordinate and audit the completed tasks. Opus 5.0 will use Sonnet subagents to exceute the tasks.  Minimize expensive token usage, use SendMessage as needed.
Codex: Top level agent will run autonomously, it will think, deisgn, plan, architect, alignment and close the loop. Use Terra subagents for focused implementation, testing, and bounded research tasks, independent quality and audit. 

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
  ATR multiples). Every new entry must have **planned reward:risk > 1.5R** at the actual
  fill, using the immutable initial stop as the R denominator. Planned R:R is reported on
  every trade and every study. Geometry locked before this 2026-07-26 amendment remains
  historical evidence only; it is never silently rewritten or promoted under the new bar.

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
- **OOS wall: 2024-01-01, immutable** (re-ratified 2026-07-12, see decisions.md). Nothing
  fits on or past it. (H3's entry families partially consumed 2025+ in the parent — caveat
  carried in HYPOTHESES.)

Process:
- decisions.md append-only, newest first; every study pre-registered (bars locked before the
  script exists); PROCEED/PARK/STOP verdicts; independent review for promotions, risk-rule
  changes, and method changes; long-running scripts resumable with elapsed/ETA.
- trades.jsonl append-only when the forward book exists; alerts (if ever) are trade events
  only.
- The 2026-07-26 success amendment applies prospectively. Existing preregs, reports, and
  verdicts remain immutable historical records, but no pre-amendment setup advances to a
  new forward entry unless it is requalified under a fresh prereg and untouched data.
