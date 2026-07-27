# ML restart Phase 0 — dependency baseline

- Completed: 2026-07-27 (America/Los_Angeles)
- Planning commit:
  `9cf63827a26662580a04b6045f612b7c3299a486`
- Initial `git status --short`: empty
- Implementation authorization: Task 1 only

## Dependency lock

`pyproject.toml` now exposes a bounded `ml` optional dependency group:

- `scikit-learn>=1.7,<2` for the locked M1 and M2 families;
- `lightgbm>=4.6,<5` for the optional M3 grouped ranker.

`uv lock` resolved 47 packages. The relevant locked versions on Python 3.12
are:

- Python 3.12.3;
- NumPy 2.5.1;
- pandas 3.0.5;
- pyarrow 25.0.0;
- scikit-learn 1.9.0;
- LightGBM 4.7.0.

An offline `uv lock` repeat left `uv.lock` byte-identical at SHA-256
`94e5dd2471448902bfbc599a3b7fbf3e8995d16d26f62d4691f3fde765deebc0`.
A frozen, offline sync of the `dev` and `ml` extras also passed.

## Synthetic compatibility gate

All checks used seeded synthetic arrays only. No repository price, catalyst,
ledger, run, or post-2023 ML data was read.

The compatibility probe imported Python, NumPy, pandas, pyarrow,
scikit-learn, and LightGBM; round-tripped a pandas frame through pyarrow; fit
each model twice on CPU; required identical predictions; and required
predictions to remain identical after a pickle serialization round-trip.
The probe covered:

- locked M1 Ridge and logistic-regression configurations;
- locked M2 histogram gradient-boosting regressor and classifier
  configurations;
- the locked M3 `LGBMRanker(objective="lambdarank")` configuration.

The isolated M3 probe ran from the frozen lock with network access disabled.
It passed with LightGBM 4.7.0 and prediction SHA-256
`cae8e9a877e286cb574db5d0c0c8ffc2c50369c4e5d900923ff893e2926d6a8f`.
LightGBM therefore passed its pre-data dependency gate and remains in the
`ml` extra.

## Verification

- Pre-change full suite: `401 passed in 28.41s`.
- Final frozen-lock full suite with `dev` and `ml`: `401 passed in 13.39s`.
- Repository-wide `ruff check --fix .`: 135 legacy findings under the
  installed Ruff 0.16.0; 104 automatically fixed and 31 remained. The 104
  unrelated mechanical edits were discarded to preserve Task 1's locked
  file scope. This is a pre-existing repository lint baseline; Task 1 adds
  no Python source.
- `git diff --check`: passed.

## Phase gate

Gate: **PASS**. The optional ML dependency set is bounded and reproducible,
the isolated LightGBM gate passed, and all synthetic compatibility and full
suite checks passed. No market-data model was fitted, no real-data ML input
was read, and no Task 2 contract or implementation was started.
