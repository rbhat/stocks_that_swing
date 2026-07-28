# ML restart Phase 4 — pre-2024 development verdict

- Completed: 2026-07-27 (America/Los_Angeles)
- Starting Task 5 commit:
  `2f1f5442f86eb2eb447f5efdf908fec9d30d754c`
- Implementation authorization: Task 5 only
- Verdict: **STOP**

## Locked run

The runner read only the deterministic Task 3 shards under
`2010-01-01 <= date < 2024-01-01`. It evaluated all 13 locked arms over four
walk-forward folds, with 20 within-date target permutations per arm/fold:

- 52 real fold attempts;
- 1,040 permutation fold attempts;
- 1,092 total attempts;
- zero selected candidates and no candidate preregs;
- zero rows observed on or after 2024-01-01.

The two complete analysis payloads were byte-identical at SHA-256
`7118ecdc934f2e2e684e50e904cbaf0fb70d6d14e457a78a30b98fd4915c4b28`.
The accepted report SHA-256 is
`1b8f6d3e0b7d8a190f187c3a1266e899e70ee82394c36a993174d77e06e8f12b`.

## Independently recomputed arm results

The table recomputes pooled means, profit totals, raw h=15 means, rows, dates,
and bar states from the four public fold records. Profit reconciliation used
the locked `1e-8` floating-point tolerance.

| Arm | Fold incremental means | Pooled / lower90 | Base / 2× net profit | Raw h15 | n / dates | Failed bars |
|---|---|---:|---:|---:|---:|---|
| A-T1-M1 | -0.1000, 0.0258, 0.0701, 0.0224 | 0.0045 / -0.0447 | 445,751 / 353,976 | 0.0084 | 5,808 / 1,936 | lower90, baselines, controls |
| A-T1-M2 | -0.0215, -0.0277, 0.0856, 0.0396 | 0.0189 / -0.0358 | 583,306 / 497,974 | 0.0146 | 5,808 / 1,936 | 3 folds, lower90, baselines, controls |
| A-T2-M1 | -0.0229, 0.0481, 0.0673, 0.0313 | 0.0310 / -0.0313 | 622,400 / 558,021 | 0.0227 | 5,808 / 1,936 | lower90, baselines, controls |
| A-T2-M2 | 0.0773, -0.0246, 0.0260, 0.0363 | 0.0287 / -0.0305 | 603,456 / 537,286 | 0.0211 | 5,808 / 1,936 | lower90, baselines, controls |
| A-T3-M1 | -0.1355, 0.1156, -0.0605, 0.2006 | 0.0284 / -0.0322 | 629,502 / 544,499 | 0.0168 | 5,808 / 1,936 | 3 folds, lower90, baselines, controls |
| A-T3-M2 | 0.0400, -0.0082, 0.0217, 0.0226 | 0.0190 / -0.0243 | 498,780 / 413,153 | 0.0137 | 5,808 / 1,936 | lower90, baselines, controls |
| B-T1-M1 | -0.0328, -0.0099, 0.0111, 0.0147 | -0.0061 / -0.0374 | 184,095 / 125,869 | 0.0077 | 3,597 / 1,199 | 3 folds, lower90, baselines, controls |
| B-T1-M2 | -0.0089, -0.0035, 0.0386, -0.0035 | 0.0060 / -0.0227 | 221,316 / 163,211 | 0.0085 | 3,597 / 1,199 | 3 folds, lower90, baselines, controls |
| B-T2-M1 | -0.0164, 0.0009, 0.0200, 0.0375 | 0.0081 / -0.0240 | 221,861 / 165,911 | 0.0108 | 3,597 / 1,199 | lower90, baselines, controls |
| B-T2-M2 | -0.0046, -0.0266, 0.0181, -0.0039 | -0.0041 / -0.0252 | 210,680 / 154,152 | 0.0087 | 3,597 / 1,199 | 3 folds, lower90, baselines, controls |
| B-T3-M1 | -0.0278, -0.0147, 0.0239, 0.0283 | 0.0001 / -0.0299 | 197,846 / 140,391 | 0.0073 | 3,597 / 1,199 | 3 folds, lower90, baselines, controls |
| B-T3-M2 | -0.0442, 0.0039, -0.0379, 0.0048 | -0.0207 / -0.0463 | 167,545 / 109,928 | 0.0080 | 3,597 / 1,199 | 3 folds, lower90, baselines, controls |
| A-T1-M3 | -0.0203, 0.1093, 0.1700, 0.1009 | 0.0900 / 0.0344 | 877,233 / 804,654 | 0.0248 | 5,808 / 1,936 | baselines, controls |

All selected rows retained valid actual-fill geometry and holds of at most 15
sessions. Absolute base/2× profits and raw h=15 means were positive for every
real arm, but those facts do not replace the locked incremental and control
bars.

## Permutation falsification failure

Eight of the 260 aggregated permutation controls cleared the real-arm economic
gate: B-T1-M1 replicates 5, 13, and 18; B-T2-M1 replicate 1; B-T2-M2
replicates 1, 4, and 14; and B-T3-M1 replicate 2. Their pooled lower90 values
ranged from 0.00036 to 0.01432.

This is a locked immediate STOP condition. The runner correctly set
`promotion_controls.permutation_arm_cleared=true`, invalidated
`required_controls_pass` for every real arm, selected zero candidates, and
returned STOP. No least-bad arm is promoted.

## Validation report

### Overall assessment: Needs revision

The report's embedded deterministic methodology/causality reviewer says
`passed` and its listed reconciliation, wall, MAE, candidate-cap, and
survivorship checks all pass. However, that reviewer omitted a required check
that no permutation arm cleared. Independent QA therefore does not accept its
headline review state as a complete methodology sign-off.

Data-quality checks otherwise reconcile the locked Task 3 evidence: 633,774
Track A rows and 29,200 Track B rows, zero duplicate keys, zero Track B
orphans, zero post-wall rows, explicit feature missingness, and no silent
zero-fill. MAE is absent from the locked matrices and is reported for every arm
as `not_run_input_failure`.

The historical roster remains survivor-biased, adjusted history may reflect
later source revisions, and point-in-time membership, delistings, and security
type are uncertified. These results are development evidence only and support
no causal or clean-OOS claim.

## Verification

- Focused Task 5 tests: `16 passed in 7.68s`.
- Full frozen-lock suite: `459 passed in 19.78s`.
- Task-scoped Ruff 0.16.0: passed.
- `git diff --check`: passed.

## Phase gate

Gate: **STOP**. Candidate count is zero. No candidate model, prereg, future
event wall, post-2023 read, collector, deployment, or portfolio work is
authorized. ML Task 6 does not begin.
