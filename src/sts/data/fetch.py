"""yfinance wrapper: split-adjusted daily OHLCV with retries.

Yahoo is an unofficial feed — every call retries with exponential backoff,
and callers must run quality checks (stm.data.quality) before using the data.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

COLUMNS = ["open", "high", "low", "close", "volume"]


class FetchError(Exception):
    pass


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Flatten yfinance output to lowercase OHLCV with a tz-naive date index."""
    if df is None or df.empty:
        raise FetchError(f"{symbol}: empty response from yfinance")
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(symbol, axis=1, level="Ticker") if "Ticker" in (df.columns.names or []) else df.droplevel(-1, axis=1)
    df = df.rename(columns=str.lower)[COLUMNS].copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "date"
    df = df.sort_index()
    return df[~df.index.duplicated(keep="last")]


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=30), reraise=True)
def fetch_daily(symbol: str, start: dt.date | None = None) -> pd.DataFrame:
    """Daily split-adjusted bars from `start` (or max history) through today.

    auto_adjust=True adjusts for both splits and dividends (total-return
    basis) — prices are not raw. Either kind of re-adjustment changes prior
    closes, which the store's overlap check (PriceStore.update) detects and
    responds to with a full rebuild.
    """
    kwargs = dict(interval="1d", auto_adjust=True, progress=False, threads=False)
    if start:
        df = yf.download(symbol, start=start.isoformat(), **kwargs)
    else:
        df = yf.download(symbol, period="max", **kwargs)
    return _normalize(df, symbol)
