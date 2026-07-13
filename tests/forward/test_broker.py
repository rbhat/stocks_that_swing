"""Tests for the PaperBroker interface and stub implementation."""

from __future__ import annotations

import datetime as dt

from sts.forward.broker import PaperBroker, StubPaperBroker, cost_side


def test_cost_side_golden_case():
    # 100 sh @ $50: 50*100*0.0005 + 1 = $3.50
    assert cost_side(price=50.0, qty=100) == 3.50


def test_stub_fills_at_supplied_open_with_correct_fees():
    def get_open(symbol: str, date: dt.date) -> float | None:
        return 50.0

    broker = StubPaperBroker(get_open=get_open)
    fill = broker.fill_entry("AAPL", dt.date(2026, 7, 10), 100)

    assert fill is not None
    assert fill["price"] == 50.0
    assert fill["fees"] == 3.50
    assert isinstance(fill["timestamp"], str)
    # Should parse as a valid ISO 8601 UTC timestamp
    dt.datetime.fromisoformat(fill["timestamp"])


def test_stub_returns_none_when_open_unavailable():
    def get_open(symbol: str, date: dt.date) -> float | None:
        return None

    broker = StubPaperBroker(get_open=get_open)
    fill = broker.fill_entry("AAPL", dt.date(2026, 7, 10), 100)

    assert fill is None


def test_stub_returns_none_when_open_non_positive():
    def get_open(symbol: str, date: dt.date) -> float | None:
        return 0.0

    broker = StubPaperBroker(get_open=get_open)
    assert broker.fill_entry("AAPL", dt.date(2026, 7, 10), 100) is None


def test_stub_returns_none_when_open_non_finite():
    def get_open(symbol: str, date: dt.date) -> float | None:
        return float("nan")

    broker = StubPaperBroker(get_open=get_open)
    assert broker.fill_entry("AAPL", dt.date(2026, 7, 10), 100) is None


def test_place_protective_and_cancel_are_noop_hooks():
    broker = StubPaperBroker(get_open=lambda symbol, date: 50.0)
    # Concrete no-op hooks on the ABC; must not raise.
    assert broker.place_protective({"entry_id": "shared:h1:AAPL:2026-07-10"}) is None
    assert broker.cancel("shared:h1:AAPL:2026-07-10") is None


def test_cost_side_custom_params():
    assert cost_side(price=100.0, qty=10, bps=10.0, per_order=2.0) == 100.0 * 10 * 0.001 + 2.0


def test_paper_broker_is_abstract():
    import inspect

    assert inspect.isabstract(PaperBroker)
