# ML-v2 Gate 2 — Source Acquisition and Point-in-Time Certification

- **Authorized:** 2026-07-28 user request, “Do the next step”
- **Status:** `STOP_INPUT`
- **Authorized source interval:** `2002-01-01 <= source date < 2026-01-01`
- **Development signal interval:** unchanged at
  `2004-01-01 <= signal date < 2026-01-01`
- **Gate 3:** not authorized

## Authority and actions

The request following completion of Gate 1 authorized the next sequential
step in `docs/PLAN.md`: source discovery, source reads, manifest construction,
and only the locked fail-closed quality checks. It did not authorize a walled
development dataset, causal feature construction, model fitting, development
simulation, selection, a prospective wall, or deployment.

The earlier start allows a conservative acquisition envelope for the
preregistered 300-session warmup. Gate 3, if it were ever authorized after a
passing Gate 2, would use a certified exchange calendar to retain exactly 300
warmup sessions and no additional pre-study rows.

## Source inventory result

The workspace contains 240 Yahoo-derived current-symbol parquet files with
1,908,689 rows and one schema. They are explicitly unsuitable for ML-v2:

- the roster is assembled from current S&P 500 and Nasdaq-100 constituents,
  so inactive and historically eligible nonmembers are absent;
- there are no permanent IDs, listing/security-type histories, historical
  symbol mappings, or delisting records;
- OHLCV is split-and-dividend adjusted rather than raw, while itemized
  corporate actions and their announcement/effective/pay timestamps are
  absent;
- all 240 files extend beyond the development cutoff, and all 240 current
  file hashes differ from the hashes in the tracked 250-symbol manifest;
- the earnings cache is absent;
- the SPY file has the same mutable adjusted-history limitation; and
- the installed generated calendar package is not an authoritative,
  content-addressed exchange extract.

The local cache inventory identity is
`cc2d7129c6ade8f25a3695fe8ccb7a3100c7e97e838eee4b5eb28cdb6f1f9a3e`.
It hashes the sorted array of file path, file hash, row count, first session,
and last session. The rejected roster-manifest hash is
`85e3fe4cdaf66ce052de0e82fee0d9b96185d1b74ccd109a8be0d54a4a22943e`.

## Acquisition candidates

Discovery identified a bounded institutional path, but no licensed extracts
or credentials are available in this workspace:

- [CRSP US Stock Databases](https://www.crsp.org/research/) are the candidate
  for PERMNO permanent IDs, name/listing histories, active and inactive US
  securities, raw daily market facts, distributions, and delisting facts.
- [LSEG Company Events](https://www.lseg.com/en/data-analytics/financial-data/company-data/company-events-coverage-data)
  is the candidate for earnings release dates/times. Certification would
  require event IDs, confirmed/estimated status, original publication
  timestamps, and the full schedule-revision lifecycle—not merely the final
  historical event date.
- An authoritative exchange calendar extract with closure and revision
  provenance is still required.

No purchase was made and no credential was created or inferred.
The planning compute/storage estimates remain unchanged because no certified
source metadata exists from which to revise row volume or extraction size.

## Deterministic artifacts

- `gate-2-source-manifest.json` records all eight required source kinds with
  provider, use constraint, available schema/coverage/as-of/revision/row/hash
  metadata, exact failures, and disposition.
- `gate-2-data-quality.json` records the fatal certification results and the
  checks not run after fatal source failure.
- `src/sts/ml_v2/source_certification.py` enforces the exact source roster,
  allowed dispositions, required certified metadata, full-interval coverage,
  canonical ordering, and fail-closed Gate status.

Source-manifest identity:
`9d911d826e7de4d9eaf78bf07625f595a80046d8af38434163537c6168d04ec7`.

Verification:

- focused Gate 2 suite: **6 passed**;
- full repository suite: **494 passed**;
- Ruff lint and format checks: **passed**;
- the committed JSON manifest reconstructs the recorded identity in a test.

## Gate result

**`STOP_INPUT`.** All eight critical source kinds are either unavailable or
rejected for leakage risk. Under the preregistration this is a completed Gate
2 outcome, not evidence of zero profitability. Gate 3 cannot begin. Resuming
ML-v2 would require the missing licensed source extracts, a new explicit Gate
2 authorization, and a fresh content-addressed certification; the rejected
Yahoo cache cannot be substituted.
