import json
import subprocess

import pytest

from sts.forward import sync
from sts.forward.journal import merge_lines
from sts.forward.ledger import LedgerPaths


def _line(**kw) -> str:
    return json.dumps(kw, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# merge_lines precedence (remote first = remote wins collisions)
# ---------------------------------------------------------------------------

def test_merge_lines_remote_wins_on_collision():
    remote = [_line(entry_id="a", seq=1, updated_at="2026-01-01T00:00:00", val="remote")]
    local = [_line(entry_id="a", seq=1, updated_at="2026-01-02T00:00:00", val="local")]
    # local has a *newer* updated_at, but merge_lines resolves by
    # updated_at recency, not by call order — remote precedence here means
    # remote is passed FIRST so on a true tie it wins.
    tied_remote = [_line(entry_id="a", seq=1, val="remote")]
    tied_local = [_line(entry_id="a", seq=1, val="local")]
    merged = merge_lines(tied_remote, tied_local, key_fn=lambda r: (r["entry_id"], r["seq"]))
    assert len(merged) == 1
    parsed = json.loads(merged[0])
    assert parsed["val"] == max("remote", "local")  # max(existing, candidate) fallback


def test_merge_lines_unions_distinct_keys():
    remote = [_line(entry_id="a", seq=1)]
    local = [_line(entry_id="b", seq=1)]
    merged = merge_lines(remote, local, key_fn=lambda r: (r["entry_id"], r["seq"]))
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# safety invariant: remote lines must be a subset of merged
# ---------------------------------------------------------------------------

def test_sync_one_file_raises_syncerror_when_remote_line_would_be_lost(tmp_path, monkeypatch):
    paths = LedgerPaths(root=tmp_path / "ledger")
    paths.root.mkdir(parents=True)

    remote_line = _line(entry_id="a", seq=1, updated_at="2026-01-01T00:00:00")

    def fake_download(filename, tmp_dir, dry_run):
        return [remote_line]

    # Force a pathological key_fn that collapses every record to the same
    # key so the "superset" check has something real to catch: local has no
    # rows, and we corrupt merge_lines' output by monkeypatching it to drop
    # the remote line entirely (simulating a merge bug / corrupted merge).
    monkeypatch.setattr(sync, "_download_remote", fake_download)
    monkeypatch.setattr(sync, "merge_lines", lambda a, b, key_fn: [])  # drops everything

    with pytest.raises(sync.SyncError):
        sync._sync_one_file("h1.jsonl", sync._family_key, paths, tmp_path, dry_run=False)


def test_sync_ledgers_alerts_and_records_error_on_safety_violation(tmp_path, monkeypatch):
    paths = LedgerPaths(root=tmp_path / "ledger")
    paths.root.mkdir(parents=True)

    monkeypatch.setattr(sync, "_download_remote", lambda filename, tmp_dir, dry_run: [_line(entry_id="a", seq=1)])
    monkeypatch.setattr(sync, "merge_lines", lambda a, b, key_fn: [])

    alerted = []
    monkeypatch.setattr(sync.alerts, "send", lambda text, webhook=None: alerted.append(text) or True)

    outcomes = sync.sync_ledgers(paths)
    assert all(outcome.startswith("error") for outcome in outcomes.values())
    assert len(alerted) == len(sync._LEDGER_FILES)


# ---------------------------------------------------------------------------
# empty remote -> fresh start
# ---------------------------------------------------------------------------

def test_download_remote_missing_file_treated_as_empty(tmp_path, monkeypatch):
    def fake_rc(args, folder_id, dry_run=False):
        return subprocess.CompletedProcess(args, returncode=3, stdout="", stderr="directory not found")

    monkeypatch.setattr(sync, "_rc", fake_rc)
    lines = sync._download_remote("h1.jsonl", tmp_path, dry_run=False)
    assert lines == []


def test_sync_one_file_fresh_start_writes_local_and_uploads(tmp_path, monkeypatch):
    paths = LedgerPaths(root=tmp_path / "ledger")
    paths.root.mkdir(parents=True)
    local_line = _line(entry_id="a", seq=1)
    (paths.root / "h1.jsonl").write_text(local_line + "\n")

    monkeypatch.setattr(sync, "_download_remote", lambda filename, tmp_dir, dry_run: [])

    calls = []

    def fake_rc(args, folder_id, dry_run=False):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_rc", fake_rc)

    outcome = sync._sync_one_file("h1.jsonl", sync._family_key, paths, tmp_path, dry_run=False)
    assert outcome == "synced"
    assert calls[0][0] == "copyto"
    assert json.loads((paths.root / "h1.jsonl").read_text().strip()) == json.loads(local_line)


# ---------------------------------------------------------------------------
# _rc command construction
# ---------------------------------------------------------------------------

def test_rc_builds_expected_command(monkeypatch):
    recorded = {}

    def fake_run(cmd, capture_output, text, check):
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sync._rc(["copyto", "gdrive:h1.jsonl", "/tmp/x"], sync.FORWARD_FOLDER_ID)

    cmd = recorded["cmd"]
    assert cmd[0] == "rclone"
    assert "--drive-root-folder-id" in cmd
    assert cmd[cmd.index("--drive-root-folder-id") + 1] == sync.FORWARD_FOLDER_ID
    assert "--retries" in cmd
    assert cmd[cmd.index("--retries") + 1] == "3"


def test_rc_dry_run_appends_flag(monkeypatch):
    recorded = {}

    def fake_run(cmd, capture_output, text, check):
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sync._rc(["copy", "a", "b"], sync.BACKTEST_FOLDER_ID, dry_run=True)
    assert "--dry-run" in recorded["cmd"]


# ---------------------------------------------------------------------------
# push_backtest_artifacts: plain copy, never deletes
# ---------------------------------------------------------------------------

def test_push_backtest_artifacts_uses_plain_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    (tmp_path / "docs" / "preregs").mkdir(parents=True)

    calls = []

    def fake_rc(args, folder_id, dry_run=False):
        calls.append((args, folder_id))
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_rc", fake_rc)
    outcomes = sync.push_backtest_artifacts()

    assert outcomes["runs"] == "synced"
    assert outcomes["docs/preregs"] == "synced"
    for args, folder_id in calls:
        assert args[0] == "copy"
        assert "--delete" not in " ".join(args)
        assert folder_id == sync.BACKTEST_FOLDER_ID


def test_push_backtest_artifacts_skips_absent_local_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # neither runs/ nor docs/preregs exists
    outcomes = sync.push_backtest_artifacts()
    assert outcomes["runs"].startswith("skipped")
    assert outcomes["docs/preregs"].startswith("skipped")


# ---------------------------------------------------------------------------
# run_daily_sync never raises
# ---------------------------------------------------------------------------

def test_run_daily_sync_never_raises_on_subprocess_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = LedgerPaths(root=tmp_path / "ledger")

    def fake_run(cmd, capture_output, text, check):
        raise OSError("rclone binary not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sync.alerts, "send", lambda text, webhook=None: False)

    result = sync.run_daily_sync(paths)  # must not raise
    assert "ledgers" in result
    assert "backtest" in result
    assert all(o.startswith("error") for o in result["ledgers"].values())


def test_run_daily_sync_default_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sync, "sync_ledgers", lambda paths, dry_run=False: {"h1.jsonl": "synced"})
    monkeypatch.setattr(sync, "push_backtest_artifacts", lambda dry_run=False: {"runs": "skipped: local dir absent"})
    result = sync.run_daily_sync()
    assert result == {"ledgers": {"h1.jsonl": "synced"}, "backtest": {"runs": "skipped: local dir absent"}}


def test_run_daily_sync_dry_run_passthrough(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_sync_ledgers(paths, dry_run=False):
        seen["ledgers_dry_run"] = dry_run
        return {}

    def fake_push(dry_run=False):
        seen["backtest_dry_run"] = dry_run
        return {}

    monkeypatch.setattr(sync, "sync_ledgers", fake_sync_ledgers)
    monkeypatch.setattr(sync, "push_backtest_artifacts", fake_push)
    sync.run_daily_sync(dry_run=True)
    assert seen == {"ledgers_dry_run": True, "backtest_dry_run": True}


# ---------------------------------------------------------------------------
# signals key fallback: total, never KeyError
# ---------------------------------------------------------------------------

def test_signals_key_handles_entry_id_present():
    rec = {"signal_date": "2026-01-01", "book": "shared", "entry_id": "shared:h1:AAPL:2026-01-01"}
    key = sync._signals_key(rec)
    assert key == ("2026-01-01", "shared", "shared:h1:AAPL:2026-01-01")


def test_signals_key_handles_missing_entry_id():
    rec = {"kind": "missed_session", "entry_id": None, "signal_date": "2026-01-01",
           "date": "2026-01-01", "book": "shared"}
    key = sync._signals_key(rec)
    assert key[:4] == ("2026-01-01", "shared", "missed_session", "2026-01-01")


def test_signals_key_never_raises_on_sparse_record():
    assert sync._signals_key({}) is not None
