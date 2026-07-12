"""Signal detector registry.

Every detector is a pure function of a config name and its params: it looks
at each session `t` using only bars `<= t` (no lookahead) and returns a
`SignalEvent` for every session that triggers. Nothing is a black box —
`SignalEvent.params` echoes the exact config used, and `trigger_values`
records the observed numbers (always including `swing_low`/`swing_high` so
the risk layer can compute Fibonacci targets).

Keep this list small and readable — no zoo of detectors. Detectors are
registered by FAMILY name; versioned config names (family_v1, family_v2 —
same detector, different params) resolve to their family, so the registry
can grow config versions without touching code. A trailing `_catalyst`
suffix (Phase 9 paired-config catalyst guard, see stm.catalyst) is stripped
BEFORE the version suffix, so e.g. `consolidation_breakout_v3_catalyst`
resolves to the same detector as `consolidation_breakout_v3` — the guard is
an engine-level param riding along in `params`, never a detector change.
"""

from __future__ import annotations

import re

import pandas as pd

from sts.models import SignalEvent
from sts.signals.breakout import detect as detect_breakout
from sts.signals.deep_pullback import detect as detect_deep_pullback
from sts.signals.markov import detect as detect_markov
from sts.signals.squeeze import detect as detect_squeeze
from sts.signals.sweep_reclaim import detect as detect_sweep_reclaim
from sts.signals.trend_pullback import detect as detect_trend_pullback

DETECTORS: dict[str, callable] = {
    "consolidation_breakout": detect_breakout,
    "vol_squeeze": detect_squeeze,
    "markov_state": detect_markov,
    "sweep_reclaim": detect_sweep_reclaim,
    "deep_pullback": detect_deep_pullback,
    "trend_pullback": detect_trend_pullback,
}

_VERSION_SUFFIX = re.compile(r"_v\d+$")
_CATALYST_SUFFIX = re.compile(r"_catalyst$")


def resolve_family(config_name: str) -> str:
    """Strip a trailing `_catalyst` suffix (once), then a trailing `_v<N>`,
    to get the detector family key. Doesn't validate the result is a known
    family — `resolve_detector` does that for dispatch; callers that just
    want the family for display (e.g. the dashboard) can use this directly."""
    name = _CATALYST_SUFFIX.sub("", config_name)
    return _VERSION_SUFFIX.sub("", name)


def resolve_detector(config_name: str):
    """Exact registry match first; else resolve to a detector family via
    `resolve_family`. Raises KeyError with the known families otherwise."""
    if config_name in DETECTORS:
        return DETECTORS[config_name]
    family = resolve_family(config_name)
    if family in DETECTORS:
        return DETECTORS[family]
    raise KeyError(
        f"unknown signal config: {config_name!r} (families: {sorted(DETECTORS)})"
    )


def detect_all(symbol: str, df: pd.DataFrame, configs: dict[str, dict]) -> list[SignalEvent]:
    """Run every named config's detector over `df` and return combined events.

    `configs` maps config_name -> params dict. Raises KeyError for a config
    name that doesn't resolve to a registered detector family.
    """
    events: list[SignalEvent] = []
    for config_name, params in configs.items():
        events.extend(resolve_detector(config_name)(symbol, df, params, config_name))
    return events
