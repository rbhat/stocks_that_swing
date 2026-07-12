"""Tests for stm.catalyst: no network, no real yfinance calls — refresh_earnings
is exercised against a monkeypatched fake yf.Ticker."""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest
import yaml

from sts.catalyst import CatalystCalendar, CatalystEvent, refresh_earnings

# Known week: Fri 2026-06-26 / Sat 2026-06-27 (weekend) / Mon 2026-06-29.
FRI = dt.date(2026, 6, 26)
SAT = dt.date(2026, 6, 27)
MON = dt.date(2026, 6, 29)
TUE = dt.date(2026, 6, 30)


def ev(symbol="AAPL", date=FRI, type_="earnings", source="earnings", note="", actions=None):
    kwargs = dict(symbol=symbol, date=date, type=type_, source=source, note=note)
    if actions is not None:
        kwargs["actions"] = actions
    return CatalystEvent(**kwargs)


# --------------------------------------------------------------------- predicate


def test_event_on_query_session_matches_horizon_0_and_1():
    cal = CatalystCalendar([ev(date=FRI)])
    assert cal.catalyst_within("AAPL", FRI, 0, "block_entry") is not None
    assert cal.catalyst_within("AAPL", FRI, 1, "block_entry") is not None


def test_event_on_next_session_matches_horizon_1_not_0():
    cal = CatalystCalendar([ev(date=MON)])
    # next session after FRI is MON (Sat/Sun aren't sessions)
    assert cal.catalyst_within("AAPL", FRI, 0, "block_entry") is None
    got = cal.catalyst_within("AAPL", FRI, 1, "block_entry")
    assert got is not None
    assert got.date == MON


def test_event_two_sessions_out_fails_horizon_1():
    cal = CatalystCalendar([ev(date=TUE)])
    # sessions after FRI: MON (1), TUE (2)
    assert cal.catalyst_within("AAPL", FRI, 1, "block_entry") is None
    assert cal.catalyst_within("AAPL", FRI, 2, "block_entry") is not None


def test_saturday_event_date_maps_to_monday_session():
    cal = CatalystCalendar([ev(date=SAT)])
    got = cal.catalyst_within("AAPL", FRI, 1, "block_entry")
    assert got is not None
    assert got.date == SAT  # stored date is the raw event date...
    # ... but effective session used for distance is Monday, i.e. matches
    # exactly like an event dated Monday would.
    got_mon = cal.catalyst_within("AAPL", MON, 0, "block_entry")
    assert got_mon is not None


def test_past_events_never_match():
    cal = CatalystCalendar([ev(date=FRI)])
    assert cal.catalyst_within("AAPL", MON, 5, "block_entry") is None


def test_action_filtering():
    cal = CatalystCalendar([ev(date=FRI, source="curated", actions=frozenset({"block_entry"}))])
    assert cal.catalyst_within("AAPL", FRI, 0, "block_entry") is not None
    assert cal.catalyst_within("AAPL", FRI, 0, "exit_before") is None


def test_unknown_symbol_returns_none():
    cal = CatalystCalendar([ev(symbol="AAPL", date=FRI)])
    assert cal.catalyst_within("ZZZZ", FRI, 5, "block_entry") is None


def test_earliest_of_multiple_returned():
    cal = CatalystCalendar([ev(date=TUE, note="later"), ev(date=MON, note="earlier")])
    got = cal.catalyst_within("AAPL", FRI, 5, "block_entry")
    assert got is not None
    assert got.date == MON
    assert got.note == "earlier"


# --------------------------------------------------------------------- load()


def test_load_missing_files_returns_empty_calendar(tmp_path):
    cal = CatalystCalendar.load(
        earnings_path=tmp_path / "nope" / "earnings.json",
        curated_path=tmp_path / "nope.yaml",
    )
    assert cal.catalyst_within("AAPL", FRI, 5, "block_entry") is None
    assert cal.coverage(["AAPL"])["total"] == 1
    assert cal.coverage(["AAPL"])["with_events"] == 0


def test_load_corrupt_earnings_json_skips_with_warning(tmp_path, caplog):
    path = tmp_path / "earnings.json"
    path.write_text("{not valid json")
    curated = tmp_path / "catalysts.yaml"
    curated.write_text("events: []\n")
    with caplog.at_level("WARNING"):
        cal = CatalystCalendar.load(earnings_path=path, curated_path=curated)
    assert cal.catalyst_within("AAPL", FRI, 5, "block_entry") is None
    assert any("catalyst" in r.message.lower() for r in caplog.records)


def test_load_malformed_yaml_entry_skipped_rest_loads(tmp_path, caplog):
    earnings = tmp_path / "earnings.json"
    earnings.write_text(json.dumps({"fetched_at": "2026-06-01T00:00:00Z", "symbols": {}}))
    curated = tmp_path / "catalysts.yaml"
    curated.write_text(
        yaml.safe_dump(
            {
                "events": [
                    {"symbol": "BAD"},  # missing date -> malformed
                    {
                        "symbol": "GOOD",
                        "date": "2026-06-26",
                        "type": "fda",
                        "note": "pdufa",
                        "action": "block_entry",
                    },
                ]
            }
        )
    )
    with caplog.at_level("WARNING"):
        cal = CatalystCalendar.load(earnings_path=earnings, curated_path=curated)
    assert cal.catalyst_within("BAD", FRI, 5, "block_entry") is None
    got = cal.catalyst_within("GOOD", FRI, 5, "block_entry")
    assert got is not None
    assert got.type == "fda"
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_load_earnings_json_populates_events(tmp_path):
    earnings = tmp_path / "earnings.json"
    earnings.write_text(
        json.dumps(
            {
                "fetched_at": "2026-06-01T00:00:00Z",
                "symbols": {
                    "AAPL": {"dates": ["2026-06-26"], "fetched_at": "2026-06-01T00:00:00Z", "error": None}
                },
            }
        )
    )
    cal = CatalystCalendar.load(earnings_path=earnings, curated_path=tmp_path / "missing.yaml")
    got = cal.catalyst_within("AAPL", FRI, 0, "block_entry")
    assert got is not None
    assert got.source == "earnings"
    assert cal.fetched_at == "2026-06-01T00:00:00Z"


# --------------------------------------------------------------------- curated yaml action mapping


def test_curated_action_default_is_both(tmp_path):
    curated = tmp_path / "catalysts.yaml"
    curated.write_text(
        yaml.safe_dump(
            {"events": [{"symbol": "XYZ", "date": "2026-06-26", "type": "lawsuit", "note": "ruling"}]}
        )
    )
    cal = CatalystCalendar.load(earnings_path=tmp_path / "missing.json", curated_path=curated)
    got = cal.catalyst_within("XYZ", FRI, 0, "block_entry")
    assert got is not None
    assert got.actions == frozenset({"block_entry", "exit_before"})
    got2 = cal.catalyst_within("XYZ", FRI, 0, "exit_before")
    assert got2 is not None


def test_curated_action_explicit_both(tmp_path):
    curated = tmp_path / "catalysts.yaml"
    curated.write_text(
        yaml.safe_dump(
            {
                "events": [
                    {"symbol": "XYZ", "date": "2026-06-26", "type": "lawsuit", "note": "x", "action": "both"}
                ]
            }
        )
    )
    cal = CatalystCalendar.load(earnings_path=tmp_path / "missing.json", curated_path=curated)
    got = cal.catalyst_within("XYZ", FRI, 0, "block_entry")
    assert got.actions == frozenset({"block_entry", "exit_before"})


# --------------------------------------------------------------------- refresh_earnings


class _FakeTicker:
    def __init__(self, symbol, plan):
        self.symbol = symbol
        self._plan = plan

    def get_earnings_dates(self, limit=12):
        action = self._plan[self.symbol]
        if action == "raise":
            raise RuntimeError("yahoo hiccup")
        idx = pd.DatetimeIndex(action).tz_localize("America/New_York")
        return pd.DataFrame({"EPS Estimate": [1.0] * len(idx)}, index=idx)


def test_refresh_earnings_schema_and_ny_conversion(tmp_path, monkeypatch):
    plan = {"AAPL": ["2026-06-26 16:00", "2026-07-30 16:00"]}

    def fake_ticker(sym):
        return _FakeTicker(sym, plan)

    import types
    fake_yf = types.SimpleNamespace(Ticker=fake_ticker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    path = tmp_path / "cache" / "catalysts" / "earnings.json"
    result = refresh_earnings(["AAPL"], path=path, per_symbol_limit=12)

    assert result["ok"] == 1
    assert result["failed"] == 0
    assert path.exists()
    payload = json.loads(path.read_text())
    assert "fetched_at" in payload
    assert payload["symbols"]["AAPL"]["dates"] == ["2026-06-26", "2026-07-30"]
    assert payload["symbols"]["AAPL"]["error"] is None


def test_refresh_earnings_merge_keeps_old_dates_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "cache" / "catalysts" / "earnings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-06-01T00:00:00Z",
                "symbols": {
                    "AAPL": {"dates": ["2026-06-26"], "fetched_at": "2026-06-01T00:00:00Z", "error": None}
                },
            }
        )
    )

    plan = {"AAPL": "raise"}

    def fake_ticker(sym):
        return _FakeTicker(sym, plan)

    import types
    fake_yf = types.SimpleNamespace(Ticker=fake_ticker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    result = refresh_earnings(["AAPL"], path=path, per_symbol_limit=12)

    assert result["ok"] == 0
    assert result["failed"] == 1
    payload = json.loads(path.read_text())
    assert payload["symbols"]["AAPL"]["dates"] == ["2026-06-26"]  # kept
    assert payload["symbols"]["AAPL"]["error"] == "yahoo hiccup"


def test_refresh_earnings_summary_counts_mixed(tmp_path, monkeypatch):
    plan = {"AAPL": ["2026-06-26 16:00"], "ZZZZ": "raise"}

    def fake_ticker(sym):
        return _FakeTicker(sym, plan)

    import types
    fake_yf = types.SimpleNamespace(Ticker=fake_ticker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    path = tmp_path / "earnings.json"
    result = refresh_earnings(["AAPL", "ZZZZ"], path=path)
    assert result["ok"] == 1
    assert result["failed"] == 1
    assert result["path"] == str(path)
    assert "elapsed_s" in result


# --------------------------------------------------------------------- coverage()


def test_coverage_counts():
    today = dt.date.today()
    future = today + dt.timedelta(days=30)
    past = today - dt.timedelta(days=30)
    cal = CatalystCalendar(
        [
            ev(symbol="AAPL", date=future),
            ev(symbol="MSFT", date=past),
            # NVDA has no events
        ]
    )
    cov = cal.coverage(["AAPL", "MSFT", "NVDA"])
    assert cov["total"] == 3
    assert cov["with_events"] == 2
    assert cov["with_upcoming"] == 1
