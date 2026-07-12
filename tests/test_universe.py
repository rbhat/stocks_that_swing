import pytest
import yaml

import sts.universe as universe_mod
from sts.universe import Universe

SEEDS = ["AAPL", "TSLA", "SPY"]


@pytest.fixture
def uni(tmp_path):
    path = tmp_path / "universe.yaml"
    path.write_text(yaml.safe_dump({"seeds": SEEDS, "discovered": []}))
    return Universe(path, tmp_path / "changes.log")


def test_add_and_persist(uni):
    assert uni.add_discovered("pltr", "volatility contraction setup")
    assert "PLTR" in uni.symbols
    reloaded = Universe(uni.path, uni.log_path)
    assert "PLTR" in reloaded.symbols
    log = uni.log_path.read_text()
    assert "ADD PLTR" in log and "volatility contraction" in log


def test_no_duplicates(uni):
    uni.add_discovered("PLTR", "x")
    assert not uni.add_discovered("PLTR", "x")
    assert not uni.add_discovered("AAPL", "already a seed")


def test_cap_rotates_weakest_discovered_never_seeds(uni, monkeypatch):
    monkeypatch.setattr(universe_mod, "MAX_SYMBOLS", 5)
    uni.add_discovered("AAA", "x")
    uni.add_discovered("BBB", "x")  # now at cap (3 seeds + 2)
    added = uni.add_discovered("CCC", "x", weakness={"AAA": 0.9, "BBB": 0.1})
    assert added
    assert "AAA" not in uni.symbols  # weakest discovered evicted
    assert all(s in uni.symbols for s in SEEDS + ["BBB", "CCC"])
    assert len(uni.symbols) == 5
    assert "ROTATE-OUT AAA" in uni.log_path.read_text()


def test_seeds_cannot_be_removed(uni):
    with pytest.raises(ValueError):
        uni.remove_discovered("AAPL", "nope")


def test_full_of_seeds_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(universe_mod, "MAX_SYMBOLS", 3)
    path = tmp_path / "u.yaml"
    path.write_text(yaml.safe_dump({"seeds": SEEDS, "discovered": []}))
    uni = Universe(path, tmp_path / "changes.log")
    with pytest.raises(RuntimeError):
        uni.add_discovered("ZZZ", "x")


def test_load_over_cap_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(universe_mod, "MAX_SYMBOLS", 2)
    path = tmp_path / "u.yaml"
    path.write_text(yaml.safe_dump({"seeds": SEEDS, "discovered": []}))  # 3 seeds > cap of 2
    with pytest.raises(ValueError):
        Universe(path, tmp_path / "changes.log")


def test_rotation_without_weakness_raises(uni, monkeypatch):
    monkeypatch.setattr(universe_mod, "MAX_SYMBOLS", 5)
    uni.add_discovered("AAA", "x")
    uni.add_discovered("BBB", "x")  # at cap
    with pytest.raises(ValueError):
        uni.add_discovered("CCC", "x")  # weakness=None
    assert "CCC" not in uni.symbols
    assert "AAA" in uni.symbols and "BBB" in uni.symbols


def test_rotation_with_incomplete_weakness_raises(uni, monkeypatch):
    monkeypatch.setattr(universe_mod, "MAX_SYMBOLS", 5)
    uni.add_discovered("AAA", "x")
    uni.add_discovered("BBB", "x")  # at cap
    with pytest.raises(ValueError):
        uni.add_discovered("CCC", "x", weakness={"AAA": 0.9})  # missing BBB
    assert "CCC" not in uni.symbols
    assert "AAA" in uni.symbols and "BBB" in uni.symbols


def test_duplicate_symbol_across_seeds_and_discovered_raises(tmp_path):
    path = tmp_path / "u.yaml"
    path.write_text(
        yaml.safe_dump({"seeds": SEEDS, "discovered": [{"symbol": "AAPL", "added": "2026-01-01", "reason": "x"}]})
    )
    with pytest.raises(ValueError):
        Universe(path, tmp_path / "changes.log")
