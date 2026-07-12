import numpy as np
import pandas as pd

from sts.data import quality

# Real NYSE sessions in June 2026
SESSIONS = ["2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"]


def make_df(dates=SESSIONS):
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="date")
    n = len(idx)
    return pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": np.full(n, 100.5),
            "volume": np.full(n, 1000),
        },
        index=idx,
    )


def test_clean_data_passes():
    assert quality.check("OK", make_df()).ok


def test_empty_fails():
    assert not quality.check("X", make_df([])).ok


def test_nan_fails():
    df = make_df()
    df.loc[df.index[1], "close"] = np.nan
    r = quality.check("X", df)
    assert not r.ok and any("NaN" in e for e in r.errors)


def test_negative_price_fails():
    df = make_df()
    df.loc[df.index[0], "low"] = -1.0
    assert not quality.check("X", df).ok


def test_high_below_low_fails():
    df = make_df()
    df.loc[df.index[2], "high"] = 90.0
    r = quality.check("X", df)
    assert any("OHLC range" in e for e in r.errors)


def test_missing_session_fails():
    df = make_df(["2026-06-25", "2026-06-29", "2026-06-30"])  # 06-26 missing
    r = quality.check("X", df)
    assert any("missing session" in e for e in r.errors)


def test_extreme_move_warns_not_fails():
    df = make_df()
    df.loc[df.index[2]:, ["open", "high", "low", "close"]] = [199.0, 201.0, 198.0, 200.0]  # ~2x jump
    r = quality.check("X", df)
    assert r.ok and any("extreme move" in w for w in r.warnings)


def test_duplicate_dates_fails():
    df = make_df(SESSIONS + ["2026-06-30"])  # 06-30 repeated
    r = quality.check("X", df)
    assert not r.ok and any("duplicate dates" in e for e in r.errors)


def test_unsorted_index_fails_without_crashing():
    df = make_df()
    df = df.iloc[::-1]  # reverse: index no longer sorted
    r = quality.check("X", df)
    assert not r.ok and any("index not sorted" in e for e in r.errors)


def test_negative_volume_fails():
    df = make_df()
    df.loc[df.index[0], "volume"] = -100
    r = quality.check("X", df)
    assert not r.ok and any("negative volume" in e for e in r.errors)


def test_zero_volume_warns_ok_stays_true():
    df = make_df()
    df.loc[df.index[0], "volume"] = 0
    r = quality.check("X", df)
    assert r.ok and any("zero-volume" in w for w in r.warnings)
