# ML-v2 Gate 1 — Pure Contracts and Synthetic Simulator

- **Authorized:** 2026-07-28 user request
- **Status:** COMPLETE
- **Data boundary:** synthetic and hand-calculated facts only
- **Next authority:** Gate 2 is not authorized

## Authority and charter boundary

The user's explicit ML-v2 Gate 1 authorization is later and more specific than
`docs/VISION.md`'s legacy paper-book `No ML` principle. It authorizes only
the preregistered independent research-study contracts and synthetic
simulator. The ML-v2 $1,000,000 fresh-fold book, 0.50% per-position risk, 10%
position cap, and Ridge/HGB identities do not amend the $100,000 paper-book
charter, authorize fitting, or permit ML-selected forward entries.

No market or vendor dataset was opened. No data adapter, model fit,
development simulation, run directory, prospective wall, forward process, or
deployment was created.

## Implemented surface

- `src/sts/ml_v2/contracts.py` — six locked complete setup contracts,
  immutable decimal market facts, synthetic-only source manifests, causal
  as-of checks, and fail-closed OHLC/session validation.
- `src/sts/ml_v2/identity.py` — canonical UTF-8 JSON, fixed decimal strings,
  domain-separated hashes, permanent-ID tie keys, control seeds, and
  hash-chained ledger identities.
- `src/sts/ml_v2/metrics.py` — exact NROCC, portfolio return, drawdown, CAGR,
  Calmar, profit factor, win/R, exposure, turnover, holding, concurrency,
  rejection, and concentration contracts.
- `src/sts/ml_v2/controls.py` — momentum, pullback, activity, seeded random,
  and synchronized score-permutation ranks over unchanged candidate pools.
- `src/sts/ml_v2/portfolio.py` — one pure event-sourced state machine for real
  and control ranks, with cash, eight slots, 80% gross allocation, 10%
  position, 1% participation, 0.50% risk, three-entry throttle, doubled
  friction, corporate actions, delistings, and deterministic resume.
- `tests/test_ml_v2_*.py` — hand calculations, synthetic canaries,
  property-style input permutations, and state-machine boundary tests.
- `coding_rules.md` — concise implementation-agent error guards.

## Deterministic implementation locks

These details were fixed before any market evidence access:

- start-of-session equity is the preceding session's closing marked equity,
  before current-session opening exits;
- pending orders are transient opening commands and do not reserve overnight
  capital or slots;
- the four initial integer caps use the raw opening print; doubled slippage is
  fixed from that preliminary size; binary search may only reduce shares;
- certified cash distributions become receivables on the ex-date, are
  included in equity, and move to cash on the payable date;
- certified delisting recovery is a cash entitlement without sell slippage or
  commission; absent recovery is zero;
- decimal square-root calculations use precision 50 and reconciliation uses a
  `1e-18` tolerance;
- reported p90 values use nearest-rank percentiles;
- no aggregate portfolio risk cap was invented; per-position initial risk is
  reserved and released with the position.

## Verification

- Focused Gate 1 suite:
  `uv run pytest -q tests/test_ml_v2_contracts.py
  tests/test_ml_v2_controls.py tests/test_ml_v2_metrics.py
  tests/test_ml_v2_portfolio.py` — **29 passed**.
- Full suite: `uv run pytest -q` — **488 passed**.
- Lint: `uvx ruff check --fix src/sts/ml_v2 tests/test_ml_v2_*.py` —
  **passed**.
- Fixed synthetic canary, invoked independently twice:
  - simulation identity:
    `f06b558e739b1078419ba3491df28fec823409a117ca070844603d7173df5f2d`;
  - canonical byte SHA-256:
    `5d33857b80d8f722b65a434108839ee5298496ac925786ccfc9fe2cf85d6f39d`.

The two invocations were byte-identical. Crash-after-durable-event replay
also reproduced the clean result byte-for-byte without duplicate event
hashes; a corrupted resume prefix failed closed.

## Gate result

**PASS.** Gate 1 is complete. Passing it does not authorize Gate 2, any data
read, model fitting, development execution, candidate selection, forward
testing, paper-book change, or deployment.
