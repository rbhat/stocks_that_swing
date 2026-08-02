from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_legacy_admin_runner.py"
    spec = importlib.util.spec_from_file_location("legacy_admin_runner_for_tests", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    module.ROOT = tmp_path
    module.LOG_ROOT = tmp_path / "logs" / "dashboard"
    module.SYNC_COMMAND = (sys.executable, "-c", "print('sync complete')")
    monkeypatch.setenv("LEGACY_ADMIN_TOKEN", "runner-secret")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "dashboard_settings.yaml").write_text(
        "discord_alerts: true\nmonitor_gap_alert_pct: 0.1\n", encoding="utf-8"
    )
    return module


def _headers() -> dict[str, str]:
    return {"X-Legacy-Admin-Token": "runner-secret"}


def test_runner_rejects_missing_token(runner):
    client = TestClient(runner.app)
    assert client.put("/config", json={"discord_alerts": False}).status_code == 403
    assert client.post("/sync").status_code == 403


def test_runner_validates_and_atomically_updates_allowlisted_config(runner):
    client = TestClient(runner.app)
    assert client.put("/config", headers=_headers(), json={"strategy": "changed"}).status_code == 422
    response = client.put(
        "/config",
        headers=_headers(),
        json={"discord_alerts": False, "monitor_dd_alert_pct": 0.2},
    )
    assert response.status_code == 200
    assert response.json()["old"] == {"discord_alerts": True, "monitor_gap_alert_pct": 0.1}
    assert response.json()["new"] == {
        "discord_alerts": False,
        "monitor_dd_alert_pct": 0.2,
        "monitor_gap_alert_pct": 0.1,
    }
    assert not list((runner.ROOT / "configs").glob("*.tmp"))


def test_runner_reports_sync_contention_and_completion(runner):
    client = TestClient(runner.app)
    runner.LOG_ROOT.mkdir(parents=True)
    (runner.LOG_ROOT / "sync.lock").write_text("busy", encoding="utf-8")
    assert client.post("/sync", headers=_headers()).status_code == 409

    (runner.LOG_ROOT / "sync.lock").unlink()
    response = client.post("/sync", headers=_headers())
    assert response.status_code == 200
    sync_id = response.json()["id"]
    state = {"status": "running"}
    for _ in range(100):
        state = client.get(f"/sync/{sync_id}", headers=_headers()).json()
        if state["status"] != "running":
            break
        time.sleep(0.01)
    assert state["status"] == "ok"
    assert state["returncode"] == 0
    durable = json.loads((runner.LOG_ROOT / f"sync-{sync_id}.json").read_text())
    assert durable["status"] == "ok"
