
import numpy as np
import pandas as pd
import pytest

from sts.ml.contracts import canonical_config_hash
from sts.ml.data import (
    TRACK_B_CELL_TO_FLAG,
    build_development_matrices,
    load_development_frames,
    write_development_artifacts,
)
from sts.ml.units import TrackBEvent
from sts.ml.walls import WallViolation


def _frame(start="2022-01-03", periods=360, offset=0.0):
    index = pd.bdate_range(start, periods=periods, name="date")
    close = pd.Series(100.0 + offset + np.arange(periods) * 0.03, index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_loader_predicate_filters_before_materialization_and_refuses_canary(
    tmp_path, monkeypatch
):
    path = tmp_path / "AAA.parquet"
    path.touch()
    seen = {}

    def fake_read(path, *, columns, filters):
        seen["columns"] = columns
        seen["filters"] = filters
        return _frame(start="2024-01-02", periods=2)

    monkeypatch.setattr(pd, "read_parquet", fake_read)
    with pytest.raises(WallViolation, match="out-of-wall"):
        load_development_frames(tmp_path, ["AAA"])
    assert ("date", "<", pd.Timestamp("2024-01-01")) in seen["filters"]
    assert seen["columns"] == ["open", "high", "low", "close", "volume"]


def test_loader_records_missing_roster_input_without_zero_filling(tmp_path):
    _frame().to_parquet(tmp_path / "SPY.parquet")
    frames, inventory = load_development_frames(tmp_path, ["AAA", "SPY"])
    assert set(frames) == {"SPY"}
    assert inventory[0] == {
        "symbol": "AAA",
        "status": "not_run_input_failure",
        "reason": "missing",
    }


def test_matrix_builder_creates_tracks_targets_and_cardinality_checks():
    frames = {"SPY": _frame(offset=1.0)}
    for index in range(20):
        frames[f"S{index:02d}"] = _frame(offset=float(index))
    signal = frames["S00"].index[320].date()
    events = (
        TrackBEvent("S00", signal, "tp-rsi6-w5"),
        TrackBEvent("S00", signal, "vc-core"),
    )
    config_hash = canonical_config_hash({"fixture": 1})

    track_a, track_b, checks = build_development_matrices(
        frames, events, config_hash=config_hash
    )

    same_day = track_a[track_a["signal_session"] == pd.Timestamp(signal)]
    assert len(same_day) == 21
    assert set(same_day["selection_status"]) == {"eligible"}
    assert np.allclose(
        same_day["relative_net_r_2x"],
        same_day["net_r_2x"] - same_day["net_r_2x"].median(),
    )
    assert set(track_b["symbol"]) == {"S00"}
    assert track_b.iloc[0]["detector_sources"] == "tp-rsi6-w5|vc-core"
    assert set(TRACK_B_CELL_TO_FLAG.values()).isdisjoint(track_b.columns)
    assert checks["track_a_duplicate_keys"] == 0
    assert checks["post_wall_rows_observed"] == 0


def test_artifact_bytes_and_manifest_are_deterministic(tmp_path):
    frame = pd.DataFrame(
        {
            "schema": ["v1"],
            "config_hash": ["0" * 64],
            "row_id": ["row"],
            "track": ["A"],
            "symbol": ["AAA"],
            "signal_session": [pd.Timestamp("2023-12-01")],
            "selection_status": ["not_run_inadequate_cross_section"],
            "adjusted_return_1": [None],
        }
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "track_a": frame,
        "track_b": frame.assign(track="B"),
        "source_inventory": [],
        "config": {"fixture": True},
        "checks": {"post_wall_rows_observed": 0},
    }
    one = write_development_artifacts(output_dir=first, **kwargs)
    two = write_development_artifacts(output_dir=second, **kwargs)
    assert one == two
    names = sorted(path.name for path in first.iterdir())
    assert names == ["manifest.json", "track_a_2023.parquet", "track_b_2023.parquet"]
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
