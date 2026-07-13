"""Tests for the Discord alert module."""

from __future__ import annotations

import datetime as dt
import json
import urllib.error

import pytest

from sts.forward import alerts


# ---------------------------------------------------------------------------
# entry_alert
# ---------------------------------------------------------------------------


def test_entry_alert_golden_string():
    cand = {
        "ticker": "NVDA",
        "entry_price_range": [123.4, 125.678],
        "tp1": 130.5,
        "sl": 118,
        "config_name": "h1:variant-a",
    }
    now = dt.datetime(2026, 7, 12, 9, 31, tzinfo=dt.timezone.utc)
    result = alerts.entry_alert(cand, now=now)
    assert result == (
        "NVDA Entry @123.40-125.68, TP1: @130.50, TP2: @-, SL: 118.00. "
        "Config: h1:variant-a. Alerted at 2026-07-12 02:31 AM PT."
    )


def test_entry_alert_uses_current_time_when_now_not_given(monkeypatch):
    cand = {
        "ticker": "AAPL",
        "entry_price_range": [10, 11],
        "tp1": 12,
        "sl": 9,
        "config_name": "h2:base",
    }
    fixed = dt.datetime(2026, 1, 1, 17, 0, tzinfo=dt.timezone.utc)

    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is not None else fixed.replace(tzinfo=None)

    monkeypatch.setattr(alerts.dt, "datetime", FakeDatetime)
    result = alerts.entry_alert(cand)
    assert "Alerted at 2026-01-01" in result


def test_entry_alert_pm_time():
    cand = {
        "ticker": "MSFT",
        "entry_price_range": [1, 2],
        "tp1": 3,
        "sl": 0.5,
        "config_name": "h1:base",
    }
    # 21:15 UTC = 14:15 PT (PDT, UTC-7) in July -> 02:15 PM PT
    now = dt.datetime(2026, 7, 12, 21, 15, tzinfo=dt.timezone.utc)
    result = alerts.entry_alert(cand, now=now)
    assert "Alerted at 2026-07-12 02:15 PM PT." in result


# ---------------------------------------------------------------------------
# book_status
# ---------------------------------------------------------------------------


def test_book_status_single_snapshot():
    snapshots = [
        {
            "book": "shared",
            "equity": 100234.5,
            "cash": 50000,
            "usd_deployed": 50234.5,
            "open_count": 3,
        }
    ]
    result = alerts.book_status(snapshots)
    assert result == (
        "shared: equity=$100234.50 cash=$50000.00 deployed=$50234.50 open=3"
    )


def test_book_status_multiple_snapshots_one_line_each():
    snapshots = [
        {"book": "shared", "equity": 100000, "cash": 40000, "usd_deployed": 60000, "open_count": 5},
        {"book": "h1solo", "equity": 100000, "cash": 100000, "usd_deployed": 0, "open_count": 0},
    ]
    result = alerts.book_status(snapshots)
    assert result == (
        "shared: equity=$100000.00 cash=$40000.00 deployed=$60000.00 open=5\n"
        "h1solo: equity=$100000.00 cash=$100000.00 deployed=$0.00 open=0"
    )


def test_book_status_empty_list():
    assert alerts.book_status([]) == ""


# ---------------------------------------------------------------------------
# exit_alert
# ---------------------------------------------------------------------------


def test_exit_alert_golden_string_positive_r():
    row = {
        "ticker": "TSLA",
        "exit_reason": "tp1",
        "exit_price": 250.125,
        "r_net": 1.5,
        "book": "shared",
    }
    result = alerts.exit_alert(row)
    assert result == "TSLA EXIT tp1 @250.12, R=+1.50 (shared)"


def test_exit_alert_golden_string_negative_r():
    row = {
        "ticker": "AMD",
        "exit_reason": "sl",
        "exit_price": 90,
        "r_net": -1.0,
        "book": "h1solo",
    }
    result = alerts.exit_alert(row)
    assert result == "AMD EXIT sl @90.00, R=-1.00 (h1solo)"


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


def test_send_missing_webhook_returns_false(monkeypatch):
    monkeypatch.delenv("DISCORD_WEB_HOOK", raising=False)
    assert alerts.send("hello") is False


def test_send_success_posts_expected_payload(monkeypatch):
    monkeypatch.setenv("DISCORD_WEB_HOOK", "https://discord.example/webhook")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["headers"] = req.headers
        return FakeResponse()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    result = alerts.send("hello world")
    assert result is True
    assert captured["url"] == "https://discord.example/webhook"
    assert captured["data"] == {"content": "hello world"}


def test_send_truncates_content_to_1900_chars(monkeypatch):
    monkeypatch.setenv("DISCORD_WEB_HOOK", "https://discord.example/webhook")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    long_text = "x" * 5000
    alerts.send(long_text)
    assert len(captured["data"]["content"]) == 1900


def test_send_explicit_webhook_param_overrides_env(monkeypatch):
    monkeypatch.delenv("DISCORD_WEB_HOOK", raising=False)
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return FakeResponse()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    result = alerts.send("hi", webhook="https://discord.example/explicit")
    assert result is True
    assert captured["url"] == "https://discord.example/explicit"


def test_send_retries_then_returns_false(monkeypatch):
    monkeypatch.setenv("DISCORD_WEB_HOOK", "https://discord.example/webhook")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise urllib.error.URLError("boom")

    sleeps = []
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(alerts.time, "sleep", lambda s: sleeps.append(s))

    result = alerts.send("hello")
    assert result is False
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_send_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("DISCORD_WEB_HOOK", "https://discord.example/webhook")
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("boom")
        return FakeResponse()

    sleeps = []
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(alerts.time, "sleep", lambda s: sleeps.append(s))

    result = alerts.send("hello")
    assert result is True
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_send_never_raises_on_unexpected_exception(monkeypatch):
    monkeypatch.setenv("DISCORD_WEB_HOOK", "https://discord.example/webhook")

    def fake_urlopen(req, timeout=None):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(alerts.time, "sleep", lambda s: None)

    result = alerts.send("hello")
    assert result is False
