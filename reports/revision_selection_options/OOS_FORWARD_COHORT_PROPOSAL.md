# VF9 / MC5 OOS and Forward Cohort Proposal

- **Status:** approved exactly as written on 2026-07-31
- **Study OOS:** opened once, evaluated, and sealed
- **Implementation:** OOS complete; unchanged forward run initialized without backfill
- **Active authority:** `docs/PLAN.md` remains the sole active, user-owned plan

## Objective

Use the one final historical OOS opening to compare two validation-selected
cohorts, then forward-paper-test both cohorts unchanged. Preserve raw results
for every strategy as well as normalized cohort views so a small number of
strategies cannot silently carry a cohort result.

## Proposed names

- OOS comparison: `swing-ranking-v1-oos-cohort-comparison-v1`
- `VF9`: Validation Frontier 9, the validation top-five union
- `MC5`: Multi-Metric Core 5, revisions in at least two validation top-five
  lists
- `FO4`: Frontier-Only 4, the four VF9 revisions outside MC5; diagnostic only
- Forward run: `swing-ranking-v1-forward-01`

`MC5` is a subset of `VF9`; `VF9 = MC5 + FO4`. Evaluate nine unique revisions,
not fourteen.

## Proposed immutable membership

| Revision | Full strategy identity | Membership | Validation evidence |
|---|---|---|---|
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5` | `8c6c38ba6f6c54e2ae6ed7614502ee3a3ebecfa44796becef7f16c8d41969785` | VF9 / FO4 | Profit #1 |
| `monthly-ema6-below__close-cross-sma10__rolling-low10__target-risk1p75` | `17e5de083ecb6ab832333135164d60c238e936b7802660cd2e7d848465c0dd44` | VF9 / FO4 | Profit #2 |
| `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-rolling-high20` | `ac431397b2740ade3c9c179562724eb9fc38691447f094aa13fbad15b3c3fa7e` | VF9 / MC5 | Profit #3, ratio #2 |
| `weekly-ema13-below__close-cross-ema5__atr14x1__target-risk1p75` | `ad135d51040e9cf5a722c352db120093738102dd5f653b21cca276c853137be6` | VF9 / MC5 | Profit #4, ratio #5 |
| `monthly-ema6-below__close-cross-sma10__rolling-low20__target-risk2p5` | `f466b2eb8f38ed4896b5012ceeeb179faed12ae663e00be7ecb773e72598e7cc` | VF9 / MC5 | Profit #5, drawdown #1, ratio #1 |
| `weekly-ema13-below__return5-cross-zero__rolling-low20__target-risk2p5` | `cd89dd0d61df5183b03f483aa5b7a1d612160b3fd8bbca26fb781394a6a750ec` | VF9 / MC5 | Drawdown #2, ratio #3 |
| `monthly-ema6-above__return5-cross-zero__rolling-low20__target-risk1p75` | `553ee87a43952a43e4f652ada5f9718e10ee05dae53ffc7d91ebda47c9bf6147` | VF9 / MC5 | Drawdown #5, ratio #4 |
| `monthly-ema6-below__return5-cross-zero__rolling-low20__target-risk2p5` | `8562be0e31877da7b9cb62754156ab6b895951dc811b54c2fe99850f0a28245a` | VF9 / FO4 | Drawdown #3 |
| `weekly-ema13-below__close-cross-sma10__atr14x1p5__target-risk1p75` | `fc0b7c9e5a8ad92b2fbff512575c9d7316506515ae307a156adb3bf22422a218` | VF9 / FO4 | Drawdown #4 |

## Evidence sequence

1. Bind the exact nine identities and the VF9, MC5, and FO4 memberships before
   reading OOS.
2. Record that VF9 and MC5 both proceed to forward paper regardless of OOS
   performance.
3. Open historical study OOS once and evaluate each of the nine revisions once.
4. Produce raw strategy results plus VF9, MC5, and FO4 cohort views; seal the
   OOS artifacts before starting forward work.
5. Start forward paper with the same identities, memberships, aggregation,
   charter, and metrics. Do not backfill.
6. Treat forward evidence as decision-ready only after at least 30 closed
   trades per revision. Interim 10- and 20-trade views are descriptive only.

Do not change membership, weights, parameters, or execution rules after OOS is
read. Do not create an alternative post-OOS cohort. There is no automatic
winner or performance kill rule.

## Evaluation model

Run each revision as one independent virtual `$100,000` strategy book using the
existing charter. Reuse the five shared books in both VF9 and MC5 views.

Report both forms:

- **Raw strategy books:** starting equity, ending equity, gross dollar P&L,
  return, maximum drawdown in dollars and percent, profit/drawdown, closed
  trades, exposure, turnover, and break-even proportional cost for every
  revision.
- **Raw cohort totals:** VF9 starts at `$900,000`; MC5 starts at `$500,000`.
  Always show the capital base beside ending equity and gross P&L because the
  totals are not directly comparable across different cohort sizes.
- **Normalized cohort indexes:** equal-weight the member strategies after
  normalizing each `$100,000` equity curve. Use these indexes for the fair VF9
  versus MC5 return comparison. Calculate cohort drawdown and
  profit/drawdown directly from each cohort curve.

For normalized equity and return attribution only:

`VF9 = (5 / 9) * MC5 + (4 / 9) * FO4`

Drawdown and profit/drawdown are path-dependent and do not decompose with that
formula.

## Concentration and breadth

Make strategy-level contribution visible rather than allowing normalization to
hide dispersion:

- raw dollar P&L by revision;
- positive versus negative revision count;
- median revision return;
- largest and top-three shares of gross positive P&L;
- losses offset against gross gains;
- leave-one-out cohort return, drawdown, and profit/drawdown for every revision;
- symbol, time, and filled-trade overlap diagnostics.

## Dashboard drilldown

### Overview

Show four standard charts:

1. **Normalized cohort equity:** full-period line chart for VF9, MC5, and FO4.
2. **Raw cohort equity:** aligned VF9 and MC5 panels with their actual dollar
   capital bases; do not overlay incompatible starting amounts.
3. **Cohort drawdown:** full-period drawdown-percent line or area chart for VF9
   and MC5, with FO4 available as a diagnostic toggle.
4. **Configuration gross P&L:** sorted horizontal positive/negative bars for
   all nine revisions with exact dollar labels and a zero line.

The default dashboard must show the full available date range. Optional zoom
must not replace the full-period view.

### Full cohort view

Clicking VF9 or MC5 opens a full-width view containing normalized equity, raw
equity, drawdown, revision contribution, closed-trade counts with a 30-trade
reference, positive/negative breadth, top-one and top-three concentration, and
leave-one-out effects.

### Full strategy view

Use a `3 x 3` grid of aligned small equity charts instead of a nine-line
spaghetti chart. Give every revision the same date range and normalized-return
scale. Show raw ending equity, gross P&L, and MC5 or FO4 membership in each
panel header.

Clicking a revision opens its raw equity, normalized return, drawdown, trade
P&L distribution, cumulative closed-trade count, exit reasons, exact ledger,
and leave-one-out cohort impact.

### OOS versus forward

Once forward evidence exists, provide `OOS`, `Forward`, and `Compare` views.
Keep the two periods separate; never join them into one continuous equity
curve. Use paired panels for cohort curves and horizontal dumbbell charts for
per-revision OOS-versus-forward return comparisons.

### Controls and visual standard

Use only these global controls:

- evidence: `OOS | Forward | Compare`;
- cohort: `VF9 | MC5 | FO4`;
- value: `Normalized % | Raw $`.

Every major chart gets a `Full view` action and an exact supporting table.
Use white backgrounds, quiet grey grids, charcoal text, blue for VF9, orange
for MC5, and grey for FO4. Use direct labels where practical. Do not use
dual axes, pies, gauges, radar charts, 3D effects, gradients, or red/green as
the only distinction. Absolute bar charts start at zero; aligned time-series
charts share the same date scale; no data are hidden through top-N truncation.

## Authorization and execution record

The user explicitly authorized all three items on 2026-07-31:

1. approve the exact nine identities and the VF9, MC5, and FO4 definitions;
2. authorize creation of the immutable OOS selection; and
3. authorize the study's one final OOS opening.

The immutable selection is
`configs/swing_ranking_v1/oos_cohort_selection.json`. Results and identities
are recorded in `docs/OOS_RESULTS.md`. Forward run
`swing-ranking-v1-forward-01` first admits signals on 2026-08-03.
