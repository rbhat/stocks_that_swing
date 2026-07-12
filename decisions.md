# Decisions

Append-only. Newest first.

---

## 2026-07-11 — Phase 0: Charter ratification

All VISION.md charter rules ratified with one amendment (short side). Decisions:

1. **Universe**: 250-name roster (parent shape). Cache already seeded — `universe.yaml`
   (12 seeds) + `cache/study_frames/` (250 parquet files) present at kickoff. Floors:
   price ≥ $5, avg dollar-vol ≥ $20M — confirmed.
2. **OOS wall**: **2025-07-01** (not the proposed 2025-01-01) — ~12 months of virgin OOS
   from kickoff. User chose this over both the 2026-01-01 alternative (too short, ~6mo,
   no year-by-year stability read possible) and the original 2025-01-01 proposal.
3. **Risk numbers**: confirmed as proposed — 0.75% risk/trade, max 8 concurrent positions,
   80% max deployed, 15% per-position notional cap, stop bound ≤12% of entry.
4. **Short side**: **off the table entirely** (AMENDS VISION.md, which proposed a
   phase-gated amendment after Phase 5). Long-only permanently for this project — no
   future short-side path assumed. VISION.md updated to reflect this.
5. **Costs**: confirmed as proposed — 5 bps/side + $1/order, mandatory 2× cost-sensitivity
   arm on every verdict.
6. **Catalyst rule**: confirmed as standing directive — no new entries within 2 sessions
   before a scheduled earnings date; holding through earnings allowed, no forced exits.
7. **Repo name / sync**: `stocks_that_swing` (matches current directory). No Drive sync
   or multi-machine setup before Phase 6.

**Status: VISION.md charter RATIFIED** (short-side clause amended per #4 above).
Proceeding to Phase 1 (port foundations from parent `stocks_that_move` at
`/Users/rajeev/dev/stocks_that_move`).
