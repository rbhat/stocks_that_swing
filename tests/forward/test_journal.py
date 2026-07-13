import json
import logging

import pytest

from sts.forward.journal import Journal, merge_lines


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "events.jsonl")


def test_append_then_read_round_trip(journal):
    journal.append({"id": 1, "value": "a"})
    journal.append({"id": 2, "value": "b"})
    records = journal.read()
    assert records == [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]


def test_append_writes_one_line_per_record(journal):
    journal.append({"id": 1})
    journal.append({"id": 2})
    lines = journal.path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"id": 1}
    assert json.loads(lines[1]) == {"id": 2}


def test_append_sorts_keys(journal):
    journal.append({"b": 2, "a": 1})
    line = journal.path.read_text().splitlines()[0]
    assert line == json.dumps({"a": 1, "b": 2}, sort_keys=True, default=str)


def test_len_reflects_record_count(journal):
    assert len(journal) == 0
    journal.append({"id": 1})
    journal.append({"id": 2})
    assert len(journal) == 2


def test_read_skips_truncated_trailing_line(journal, caplog):
    journal.append({"id": 1})
    journal.append({"id": 2})
    # Manually truncate the last line to simulate a crash mid-write.
    with open(journal.path, "a") as f:
        f.write('{"id": 3, "value": "incompl')
    with caplog.at_level(logging.WARNING):
        records = journal.read()
    assert records == [{"id": 1}, {"id": 2}]
    assert any("truncat" in rec.message.lower() or "skip" in rec.message.lower() for rec in caplog.records)


def test_read_raises_on_invalid_non_trailing_line(journal):
    with open(journal.path, "w") as f:
        f.write(json.dumps({"id": 1}) + "\n")
        f.write("not valid json\n")
        f.write(json.dumps({"id": 3}) + "\n")
    with pytest.raises(ValueError, match="2"):
        journal.read()


def test_read_on_missing_file_returns_empty(tmp_path):
    j = Journal(tmp_path / "missing.jsonl")
    assert j.read() == []
    assert len(j) == 0


def _line(d):
    return json.dumps(d, sort_keys=True, default=str)


def test_merge_lines_unions_preserving_order():
    a = [_line({"key": "x", "updated_at": 1}), _line({"key": "y", "updated_at": 1})]
    b = [_line({"key": "y", "updated_at": 1}), _line({"key": "z", "updated_at": 1})]
    merged = merge_lines(a, b, key_fn=lambda d: d["key"])
    keys = [json.loads(l)["key"] for l in merged]
    assert keys == ["x", "y", "z"]


def test_merge_lines_dedupes_exact_duplicates():
    a = [_line({"key": "x", "updated_at": 1})]
    b = [_line({"key": "x", "updated_at": 1})]
    merged = merge_lines(a, b, key_fn=lambda d: d["key"])
    assert len(merged) == 1


def test_merge_lines_collision_keeps_larger_updated_at(caplog):
    a = [_line({"key": "x", "updated_at": 1, "value": "old"})]
    b = [_line({"key": "x", "updated_at": 2, "value": "new"})]
    with caplog.at_level(logging.WARNING):
        merged = merge_lines(a, b, key_fn=lambda d: d["key"])
    assert len(merged) == 1
    assert json.loads(merged[0])["value"] == "new"
    assert len(caplog.records) == 1


def test_merge_lines_collision_fallback_raw_string_when_no_updated_at():
    a = [_line({"key": "x", "value": "aaa"})]
    b = [_line({"key": "x", "value": "bbb"})]
    merged = merge_lines(a, b, key_fn=lambda d: d["key"])
    # Larger raw string wins (fallback comparison), deterministic result.
    expected = max(a[0], b[0])
    assert merged[0] == expected


def test_merge_lines_is_idempotent():
    a = [_line({"key": "x", "updated_at": 1})]
    b = [_line({"key": "x", "updated_at": 2}), _line({"key": "y", "updated_at": 1})]
    once = merge_lines(a, b, key_fn=lambda d: d["key"])
    twice = merge_lines(once, b, key_fn=lambda d: d["key"])
    assert once == twice
