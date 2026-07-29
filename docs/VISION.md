CRITICAL: THIS FILE IS ONLY USER EDITABLE. AGENTS SUGGEST CHANGES IF NEEDED.

# Vision

Build a daily-data swing-trading engine that finds and paper-trades **3–21 session moves** in
liquid US stocks using multi-timeframe technical setups — higher-timeframe trend and levels
choosing *where* to look, daily-timeframe triggers choosing *when* to act — with risk sized to
swing-scale volatility, validated by pre-registered studies against history, and proven by a
fast-accruing forward paper book. Paper only; real money never, unless explicitly authorized
much later.
The idea is to have many small resolutions per year instead of a few large ones.

The repository's Yahoo-derived current-roster cache is accepted for bounded
historical screening with explicit survivorship and adjusted-history
limitations. Forward paper results provide the next evidence after the user
selects a mix. The sole plan is `docs/PLAN.md`.


**Success looks like:**
- Retrospective screening produces a reproducible top-five ranking by gross
  profit, drawdown, and profit/drawdown, followed by the user's choice of
  strategies for forward paper testing. No trading cost is assumed or
  deducted. The current-roster screen is not called untouched OOS. Every
  initial stop must risk **< 25% of entry**.
  These are entry-time geometry bars; realized
  winners are reported as a distribution, not forced to exceed 1.5R after the fact.
- A forward paper book whose realized gross return is compared with the
  matched-trade-count retrospective screening gross-return band after
  **≥ 30 closed trades** — swing velocity makes this cheap; forward evidence is
  the arbiter, and here it arrives in months, not years.
- Median hold ≤ 21 sessions; every trade carries its setup, trigger, stop, target, and time
  stop at entry — nothing is a black box.
- Drawdown reported against the charter reference — Turnover and break-even cost are
  reported without assuming a commission, spread, fee, or slippage. 

**The honest kill criterion - User Override:** None. Rank top 5 setups in terms of Profit, Drawdown and Profit/Drawdown ratio. Let the user decide the mix of strategies to use for forward testing.

**Principles:**
- **Swing-native geometry.** Risk is anchored to the instrument's own volatility (ATR) and
  structure, never to a fixed percent designed for multi-year holds. The >1.5R planned
  reward:risk bar is a prospective entry-quality constraint. The bar must not
  be met by widening stops, extending the 21-session hold, or relabeling old studies.
- **Edge before ops.** No dashboard, no alerts, till user asks for it.
- **Evidence discipline inherited whole** (LESSONS §5): pre-registration before any script,
  explicit retrospective cutoffs and prospective walls, append-only decision ledger,
  event-level judging on a wide roster, independent review before promotions, distributions
  over lucky paths. Historical current-roster screens are never mislabeled untouched OOS.
- **No assumed trading costs.** Rankings use gross simulated P&L. Turnover,
  order count, profit per dollar turned over, and break-even proportional cost
  are reported so the user can judge cost sensitivity without embedding a
  commission, spread, fee, or slippage assumption.
- **Multi-timeframe, small and readable.** Signal and execution rules remain human-readable.
  ML may rank an already-fixed candidate pool; it cannot invent signals, change geometry,
  override risk. It can only use the available backtest data and can use it fully.

---

***Agent behavior***
Common: You're a technical-analysis trader with 20 years of experience, and a strong senior AI/ML engineer who architects and builds the simplest thing that works. No anti-patterns, no shortcuts, no forcing design or code, and never change the underlying strategy or education. Test what you build and audit it against these goals. Be concise and to the point, don't overexplain, go deeper when I ask.
Tell implementation subagents to give upto top 3 common errors and lets this to the coding rules to avoid. Add to coding_rules.md and point to it for agent runs. Keep it bullet point, clear and concise. Dont add explanation, history, reasoning or anything else to it.
Always use ruff --fix, not bare ruff. 
Use .scratch/ folder to create and execute temporary files and scripts. DO NOT ASK PERMISSIONS IN THIS REPO FOR BASH COMMANDS - YOU ARE AUTHORIZED.
DO NOT ADD CHANGELOG TO PLANS, DOCS, STRATEGIES and REPORTS. Keep them focused and concise. p[]

****Claude****: Top level agent will think, deisgn, plan, architect and close the loop. Top level agent will use Opus 5.0 subagent to orchestrate, coordinate and audit the completed tasks. Opus 5.0 will use Sonnet subagents to exceute the tasks.  Minimize expensive token usage, use SendMessage as needed.
****Codex****: Top level agent will run autonomously, it will think, deisgn, plan, architect, alignment and close the loop. Use Terra subagents for focused implementation, testing, and bounded research tasks, independent quality and audit.

---

## Charter rules — RATIFIED 2026-07-11 (see decisions.md)

Capital & sizing:
- $100,000 simulated starting capital. Paper trading only.
- Per-trade risk: **0.75% of equity** (position size = risk budget ÷ stop distance).
- Per-position notional cap 15%; max **8 concurrent positions**; max 80% of equity deployed.
- Long only, permanently (ratified 2026-07-11: short side is off the table for this
  project, not merely phase-gated).

Stops & exits:
- Every position has a hard stop at entry study-determined; stop distance sanity-bounded to
  ≤ 12% of entry. Never widened. Never average down.
- **Time stop: 21 sessions, hard**
- Targets are study-determined (structure: prior swing high / measured move / mean touch; or
  ATR multiples).

Entries & catalysts:
- No new entries within **2 sessions before** a scheduled earnings date; holding through
  earnings is allowed — no pre-event forced exits (user constraint, 2026-07-11). 

Universe & data:
- Liquid US common stocks/ETFs: price ≥ $5, average dollar volume ≥ $20M; roster ~150–250
  names + SPY/QQQ anchors; survivorship caveat stated on every artifact (the feed returns
  survivors — forward paper is the survivorship-free arbiter).
- Data hard rules inherited verbatim from the parent: local parquet cache is the source of
  truth; atomic writes (temp + fsync + replace); validate-before-write quality gate;
  split- and dividend-adjusted total-return basis, never mixed; incomplete bars never cached;
  jobs idempotent and resumable with ETA.

Process:
- decisions.md records the active decision; every study fixes its research
  protocol and candidate grammar before performance is read. Strategy rules
  may be explored inside that grammar. The user decides the forward mix;
  independent review is required for integrity, risk-rule, and method changes.
  Long-running scripts are resumable with elapsed/ETA.
- trades.jsonl append-only when the forward book exists; alerts (if ever) are trade events
  only.
- Historical evidence remains historical. No earlier setup enters the active
  top five or forward mix unless it is evaluated under `docs/PLAN.md`.
