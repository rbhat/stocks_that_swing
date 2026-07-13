# Plan

Each phase gates the next. The heart of the project is Phase 3 — everything before it is the
minimum harness needed to run honest studies; everything after it exists only if a study
survives. Estimated effort assumes part-time sessions.

**Guardrail (see VISION.md "No shared surface with the parent"):** LESSONS §7's ported files
are infrastructure only. Every risk, sizing, stop, target, and exit rule in this plan is
designed fresh from the charter numbers in VISION.md — never copied from the parent's
defaults, even when a ported file (e.g. `eventsim.py`'s shape) came from there originally.
When a phase says "port," read it as "port the mechanical pattern, redesign the numbers."

## Phase 0 — Charter ratification (user, ~1 session)

Walk the decision list below; record each answer in a fresh `decisions.md` (append-only,
newest first); mark VISION.md's proposed rules ratified. Nothing else happens first.

**Decision list:**
1. **Universe** — clone the parent's 250-name study-roster shape (recommended: consistency +
   statistical power), or a curated ~150 liquid/high-beta list? Eligibility floors ($5, $20M
   dollar-vol) confirmed?
2. **OOS wall** — keep 2025-01-01 (recommended; ~18 months of OOS exists on day one), noting
   the H3 partial-consumption caveat?
3. **Risk numbers** — 0.75% per trade, 8 positions, 80% deployed, 15% notional cap, ≤12% stop
   bound: confirm or set your own.
4. **Short side** — phase-gated amendment after Phase 5 (recommended), or off the table
   entirely?
5. **Costs** — 5 bps/side + $1/order (parent's numbers) with a mandatory 2× sensitivity arm on
   every verdict: confirm.
6. **Catalyst rule** — confirm the standing directive (2-session pre-earnings entry embargo;
   holding through allowed).
7. **Repo name** and whether Drive sync / multi-machine is ever wanted (recommend: not before
   Phase 6).

## Phase 1 — Port the foundations (~2–3 sessions)

Copy the parent's battle-tested modules (exact list: LESSONS §7) — calendar, fetch, store,
quality gate, env, atomic-write patterns, test patterns. Fresh cache; fetch the roster
(resumable, budgeted, ~2M bars). Suite green. **Gate:** second fetch run is a no-op;
quality-gate rejects a corrupted frame in a test.

## Phase 2 — Swing risk engine + study harness (~2–3 sessions)

The one genuinely new build:
- `risk.py` (new, swing-native): ATR/structure stops, structure/ATR targets, 15-session time
  stop, 0.75% stop-based sizing. Small, pure, unit-tested.
- Port the parent's event-simulator pattern (`eventsim.py`): every detector event simmed
  independently through the swing exit structure — the instrument every study uses.
- Two-layer read built in from day one: (a) raw forward returns at h=5/10/15 sessions
  (exit-free signal quality), then (b) exit-simmed expectancy — a family that only wins under
  layer (b) is an exit artifact.
- Weekly-bar resampler with shift-safety (a weekly bar exists only after its Friday close) +
  shift-guard tests, for the multi-timeframe conditions.
- Prereg template (bars, slices, adequacy floors, cost arms) checked into the repo.

**Gate:** negative control — random entries through the harness yield ~zero gross expectancy
minus friction; shift-guard tests green.

## Phase 2.5 — Exploratory discovery pass (~2–4 sessions; optional, feeds Phase 3)

**Purpose:** use the full IS window and any technique (grid sweeps, feature screens, ML models
— classifiers/rankers on engineered features, clustering, whatever surfaces a pattern) to
*generate* candidate hypotheses/configs, not to *validate* them. This is where "try everything
and see what works" belongs — it is explicitly barred from Phase 3's confirmatory studies
(HYPOTHESES §0, PREREG_TEMPLATE) because judging on the same data you searched is how the
parent project got burned (LESSONS).

**Hard rule — the OOS wall is load-bearing here too:** every exploratory run, sweep, or model
fit in this phase uses only data strictly before 2024-01-01. No OOS bar, slice, or event is
read, plotted, or fed to a model at any point in this phase — not even "just to look." A
pattern discovered by peeking at OOS is not a discovery, it's a leak, and it poisons every
study built on it afterward.

**Output is candidates, never verdicts.** This phase cannot itself produce PROCEED / PARK /
STOP — it has no locked prereg and no untouched OOS to judge against, so nothing it produces is
evidence. Its only deliverable is a short list of named, specific configs (or a frozen model
spec: architecture, features, training window) worth preregistering — added to HYPOTHESES.md
as new H-entries or as refinements to existing ones (e.g. "H1 cell narrowed to X based on IS
screen").

**Promotion path (mandatory):** a candidate that looks good here does not skip Phase 3. It
gets its own dated prereg (PREREG_TEMPLATE.md) naming that exact config/model as the primary
cell, locked before it ever sees OOS data, then runs through Phase 3's normal two-layer read
and locked bars. The IS performance from this phase is disclosed in that prereg as a *prior*,
never substituted for the OOS verdict.

**Gate:** none in the pass/fail sense — this phase can't fail, only produce zero, one, or many
candidates. Optional: skip it entirely if the named H1–H3 families already look sufficient.

## Phase 3 — Hypothesis studies (the heart; ~2–5 days each incl. review)

Run the families in HYPOTHESES.md priority order: **H1 trend-conditioned pullback → H2
earnings-reaction drift → H3 re-geometried breakouts**, then one exploratory round (H4, with
the user-proposed H6 setups as its named backlog) if warranted. Per study: prereg locked
before the script → run (resumable, ETA) → verdict entry in decisions.md → independent review
of any PROCEED.

**Gate per family:** its locked bars (shape in HYPOTHESES §bars). **Project kill criterion:**
all families PARK/STOP → record the STOP; do not invent H6 to keep the lights on.

## Phase 4 — Portfolio expression + validation gate (~2–3 sessions per survivor)

Surviving families become configs in a real portfolio backtest: sizing, position caps, slot
contention, both cost arms. Judged **absolutely** (positive net return, drawdown inside
charter cap, exposure floor, expectancy stable) with SPY buy-and-hold reported for reference —
never as a relative-MAR duel (parent lesson: that duel judges the tape, not the strategy).
Validation gate is gate-v2-shaped but swing-calibrated: event-level OOS n (large by
construction), year-by-year stability with a neutral band, fixed-horizon bootstrap, param
jitter. Folds sized so a fold ≫ max hold — trivial at 15 sessions (a structural advantage:
swing suffers no censoring problem).

**Stretch (only over survivors):** the cross-config confluence study (HYPOTHESES §H6) —
whether independent setups *agreeing* on an entry zone beats any single config — lives here,
prereg'd, never as an all-configs-at-once fishing pass.

**Gate:** locked prereg + independent review.

## Phase 5 — Forward paper book (ongoing; decision point ~3 months in)

Persistent paper portfolio, backtest-identical semantics, idempotent daily job — port the
parent's forward-engine pattern. Runs locally on a laptop cron; no VM. Review cadence weekly.
**Promotion prereg locked while the book is blind** (parent 10c pattern): n ≥ 30 closed,
≥ 3 months live, realized expectancy > 0 and inside the OOS band, no divergence flag.

## Phase 6 — Ops (only after Phase-5 survival)

Alerts (trade events only), minimal dashboard, VM/cron — all portable from the
parent in days precisely because it built them well. Deliberately last.

**Remote deploy:** GCP always-free `e2-micro` VM (Debian 12 + Docker, IAP-tunneled SSH,
no public IP), same pattern as the parent's `stm-daily` instance — `deploy/provision.sh`
(idempotent create + Docker install) and `deploy/deploy.sh` (scp `.env`/secrets/configs,
build+push image, install cron entries idempotently). Cron runs the daily pipeline on a
weekday schedule via `docker compose run --rm daily`, logging to the VM. Ported directly
from the parent, adapted for this repo's config/secrets layout. Shipped 2026-07 — see
docs/FORWARD_OPS.md "Remote deployment".

**Discord webhook message format** (trade-event alerts only):

```
{ticker} Entry @{price_low}-{price_high}, TP1: @{tp1}, TP2: @{tp2}, SL: {sl}. Config: {config_name}. Alerted at {timestamp PT}.
```

- `{price_low}-{price_high}`: entry price range, same precision as the config's price series.
- `TP1`/`TP2`: numeric targets, `@`-prefixed.
- `SL`: stop-loss level, no `@` prefix.
- `{config_name}`: the surviving Phase-4 config identifier (family + variant).
- `{timestamp PT}`: alert fire time in US Pacific, e.g. `2026-07-12 09:31 AM PT`.

---

**Rough arc:** Phases 0–2 ≈ one week of sessions. Each Phase-3 study days, not weeks. A
first forward book could be live within ~a month of kickoff; forward n ≥ 30 lands ~2–4 months
after that. The parent's swing arc burned most of its calendar on gate relitigation — this
plan spends it on studies instead.
