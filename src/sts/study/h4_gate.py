"""Phase-4 validation-gate stats: bootstrap expectancy, year-by-year
stability classification, and one-at-a-time jitter grids for param
sensitivity — the "gate-v2" stats the Phase-4 preregs cite alongside the
absolute bars. Pure, deterministic aside from the bootstrap's fixed seed.
"""

from __future__ import annotations

import numpy as np


def bootstrap_expectancy(r_values: list[float], n_boot: int = 5000, seed: int = 20260712) -> dict:
    """Percentile bootstrap on the mean of `r_values`. `mean` is the observed
    sample mean (never randomized); `lower90` is the 10th percentile of
    `n_boot` resampled means (one-sided 90% lower confidence bound);
    `p_negative` is the fraction of resampled means that fall below zero.
    Empty input returns `mean=0.0, lower90=None, p_negative=None`.
    Deterministic for a fixed `seed` (no reliance on global RNG state)."""
    arr = np.asarray(r_values, dtype=float)
    n = arr.size
    if n == 0:
        return {"mean": 0.0, "lower90": None, "p_negative": None}
    mean = float(arr.mean())
    if np.all(arr == arr[0]):
        # A constant array's bootstrap distribution is the constant itself —
        # skip resampling so this degenerates exactly, no RNG artifact.
        return {"mean": mean, "lower90": mean, "p_negative": 0.0 if mean >= 0 else 1.0}

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = arr[idx].mean(axis=1)
    lower90 = float(np.percentile(boot_means, 10))
    p_negative = float(np.mean(boot_means < 0))
    return {"mean": mean, "lower90": lower90, "p_negative": p_negative}


def year_stability(by_year: dict, neutral_band: float = 0.05) -> dict:
    """Classify each year's `expectancy_r_net` as "positive"/"negative"/
    "neutral" (neutral when `|expectancy_r_net| <= neutral_band`, band edges
    inclusive). `worst_year` is the year with the lowest expectancy (None if
    `by_year` is empty)."""
    years: dict[str, str] = {}
    n_positive = n_negative = n_neutral = 0
    worst_year = None
    worst_val = None
    for year, stats in sorted(by_year.items()):
        val = stats["expectancy_r_net"]
        if abs(val) <= neutral_band:
            label = "neutral"
            n_neutral += 1
        elif val > 0:
            label = "positive"
            n_positive += 1
        else:
            label = "negative"
            n_negative += 1
        years[year] = label
        if worst_val is None or val < worst_val:
            worst_val = val
            worst_year = year

    return {
        "years": years,
        "n_positive": n_positive,
        "n_negative": n_negative,
        "n_neutral": n_neutral,
        "worst_year": worst_year,
    }


def jitter_grid(params: dict, jitter_keys: dict[str, list]) -> list[dict]:
    """Cartesian one-at-a-time perturbations of `params`: for each key in
    `jitter_keys`, each of its listed values is substituted alone (every
    other key stays at its locked `params` value), producing one variant
    dict per (key, value) pair. Grid size = sum of len(values) across
    `jitter_keys`."""
    grid: list[dict] = []
    for key, values in jitter_keys.items():
        for value in values:
            variant = dict(params)
            variant[key] = value
            grid.append(variant)
    return grid
