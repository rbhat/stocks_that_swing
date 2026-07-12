import pandas as pd
import pytest

from sts.data.fetch import FetchError, _normalize

DATES = pd.to_datetime(["2026-06-25", "2026-06-26", "2026-06-29"])


def yf_style_frame(tz=None, ticker="AAPL"):
    """Mimic yf.download output: capitalized MultiIndex (Price, Ticker) columns."""
    idx = pd.DatetimeIndex(DATES, name="Date")
    if tz:
        idx = idx.tz_localize(tz)
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], [ticker]], names=["Price", "Ticker"]
    )
    data = [[100.0, 101.0, 99.0, 100.5, 1000]] * len(idx)
    return pd.DataFrame(data, index=idx, columns=cols)


def test_normalize_flattens_multiindex_and_lowercases():
    out = _normalize(yf_style_frame(), "AAPL")
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.index.name == "date"
    assert len(out) == 3


def test_normalize_strips_timezone():
    out = _normalize(yf_style_frame(tz="America/New_York"), "AAPL")
    assert out.index.tz is None
    assert out.index[0] == pd.Timestamp("2026-06-25")


def test_normalize_dedupes_keeping_last():
    df = yf_style_frame()
    dup = pd.concat([df, df.iloc[[-1]] * 2])  # duplicate last date, different values
    out = _normalize(dup, "AAPL")
    assert not out.index.duplicated().any()
    assert out.loc["2026-06-29", "close"] == 201.0  # kept the later row


def test_empty_response_raises():
    with pytest.raises(FetchError):
        _normalize(pd.DataFrame(), "AAPL")
    with pytest.raises(FetchError):
        _normalize(None, "AAPL")
