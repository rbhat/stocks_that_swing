"""Tests for sts.study.h4_gate (Phase 4 Task 3)."""

from __future__ import annotations

from sts.study.h4_gate import bootstrap_expectancy, jitter_grid, year_stability


def test_bootstrap_constant_array_mean_exact_and_lower90_equals_mean():
    out = bootstrap_expectancy([2.0, 2.0, 2.0, 2.0], n_boot=500)
    assert out["mean"] == 2.0
    assert out["lower90"] == 2.0
    assert out["p_negative"] == 0.0


def test_bootstrap_seed_determinism():
    vals = [1.0, -0.5, 2.0, -1.0, 0.3, 0.7, -0.2]
    a = bootstrap_expectancy(vals, n_boot=1000, seed=20260712)
    b = bootstrap_expectancy(vals, n_boot=1000, seed=20260712)
    assert a == b


def test_bootstrap_different_seed_can_differ():
    vals = [1.0, -0.5, 2.0, -1.0, 0.3, 0.7, -0.2]
    a = bootstrap_expectancy(vals, n_boot=1000, seed=1)
    b = bootstrap_expectancy(vals, n_boot=1000, seed=2)
    assert a["mean"] == b["mean"]  # mean of the observed data never varies
    # but the bootstrap distribution (lower90) may differ across seeds
    assert isinstance(a["lower90"], float)


def test_year_stability_classification_and_neutral_band_edges():
    by_year = {
        "2022": {"n": 10, "expectancy_r_net": 0.10},
        "2023": {"n": 10, "expectancy_r_net": -0.10},
        "2024": {"n": 10, "expectancy_r_net": 0.05},   # exactly at the band edge -> neutral
        "2025": {"n": 10, "expectancy_r_net": -0.05},  # exactly at the band edge -> neutral
        "2026": {"n": 10, "expectancy_r_net": 0.0501},  # just above band -> positive
    }
    out = year_stability(by_year, neutral_band=0.05)
    assert out["years"]["2022"] == "positive"
    assert out["years"]["2023"] == "negative"
    assert out["years"]["2024"] == "neutral"
    assert out["years"]["2025"] == "neutral"
    assert out["years"]["2026"] == "positive"
    assert out["n_positive"] == 2
    assert out["n_negative"] == 1
    assert out["n_neutral"] == 2
    assert out["worst_year"] == "2023"


def test_year_stability_empty():
    out = year_stability({})
    assert out["n_positive"] == out["n_negative"] == out["n_neutral"] == 0
    assert out["worst_year"] is None


def test_jitter_grid_size_and_one_key_at_a_time():
    base = {"atr_stop_multiple": 2.0, "atr_target_multiple": 2.0, "atr_window": 14}
    jitter_keys = {"atr_stop_multiple": [1.5, 2.5], "atr_window": [10, 18, 21]}
    grid = jitter_grid(base, jitter_keys)
    assert len(grid) == 2 + 3

    for variant in grid:
        diffs = {k for k in base if variant[k] != base[k]}
        assert len(diffs) == 1
        # every other key retains its locked base value
        for k in base:
            if k not in diffs:
                assert variant[k] == base[k]

    stop_values = sorted(v["atr_stop_multiple"] for v in grid if v["atr_stop_multiple"] != base["atr_stop_multiple"])
    assert stop_values == [1.5, 2.5]
