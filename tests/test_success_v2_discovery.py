import datetime as dt

import pandas as pd
import pytest

from sts.study import success_v2_discovery as discovery
from sts.study.success_gate import entry_geometry


def _frame(start: str = "2022-01-03", periods: int = 500) -> pd.DataFrame:
    index = pd.bdate_range(start=start, periods=periods)
    index.name = "date"
    close = pd.Series(
        [100.0 + 0.05 * i for i in range(periods)],
        index=index,
    )
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


def test_filtered_loader_never_returns_post_wall_rows(tmp_path):
    root = tmp_path / "frames"
    root.mkdir()
    frame = _frame(start="2023-01-02", periods=300)
    frame.to_parquet(root / "AAA.parquet")

    frames, manifest = discovery.load_is_frames(
        root,
        start_inclusive=dt.date(2023, 1, 1),
        end_exclusive=dt.date(2024, 1, 1),
        minimum_filtered_rows=200,
    )

    assert max(frames["AAA"].index.date) < dt.date(2024, 1, 1)
    assert manifest[0]["last_date"] < "2024-01-01"
    assert manifest[0]["filtered_content_sha256"]


def test_loader_fails_closed_if_backend_returns_post_wall_row(
    tmp_path, monkeypatch
):
    path = tmp_path / "AAA.parquet"
    path.touch()
    seen = {}

    def fake_read(path, filters):
        seen["filters"] = filters
        return _frame(start="2024-01-02", periods=2)

    monkeypatch.setattr(pd, "read_parquet", fake_read)
    with pytest.raises(RuntimeError, match="data-wall violation"):
        discovery.load_is_frames(
            tmp_path,
            start_inclusive=dt.date(2010, 1, 1),
            end_exclusive=dt.date(2024, 1, 1),
            minimum_filtered_rows=1,
        )
    assert ("date", "<", pd.Timestamp("2024-01-01")) in seen["filters"]


def test_supplied_post_wall_frame_is_refused_before_discovery():
    config = {
        "data": {
            "start_inclusive": "2010-01-01",
            "end_exclusive": "2024-01-01",
            "catalyst_path": "missing.json",
        },
        "families": {},
        "geometry": {},
        "costs": {},
        "selection": {},
        "negative_control": {"seed": 1},
    }
    with pytest.raises(RuntimeError, match="data-wall violation"):
        discovery.run_discovery(
            config,
            {"AAA": _frame(start="2024-01-02", periods=2)},
            input_manifest=[],
            catalyst_exists=False,
        )


def test_missing_catalyst_is_input_failure_not_zero_event_result():
    config = {
        "data": {
            "start_inclusive": "2010-01-01",
            "end_exclusive": "2024-01-01",
            "catalyst_path": "cache/catalysts/earnings.json",
        },
        "families": {
            "post_earnings_drift": {
                "detector": "pead_catalyst_required",
                "required_input": "cache/catalysts/earnings.json",
            }
        },
        "geometry": {},
        "costs": {},
        "selection": {},
        "negative_control": {"seed": 1},
    }
    artifact = discovery.run_discovery(
        config,
        {"SPY": _frame(start="2022-01-03", periods=300)},
        input_manifest=[],
        catalyst_exists=False,
    )

    family = artifact["families"]["post_earnings_drift"]
    assert family["state"] == "not_run_input_failure"
    assert family["reason"] == "catalyst_cache_missing"
    assert family["cells"] == []
    assert artifact["verdict"] == "STOP"


def test_screen_config_geometry_passes_strict_entry_contract():
    config = discovery.load_config("configs/success_v2_phase3.yaml")
    geometry = config["geometry"]
    judged = entry_geometry(
        100.0,
        100.0 - geometry["stop_atr_multiple"] * 2.0,
        100.0 + geometry["target_atr_multiple"] * 2.0,
    )
    assert judged["valid"]
    assert judged["planned_r"] > 1.5
    assert geometry["time_stop_sessions"] == 15
    assert len(config["families"]) == 3
    assert all(
        len(family["cells"]) <= 3
        for family in config["families"].values()
    )
