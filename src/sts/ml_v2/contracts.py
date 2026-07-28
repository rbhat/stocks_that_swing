"""Fail-closed, I/O-free ML-v2 setup and synthetic input contracts."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from sts.ml_v2.identity import identity_hash, require_sha256, setup_identity

STUDY_ID = "ml-v2"
LOCKED_SETUP_IDS = ("P-D", "P-R", "P-H", "B-D", "B-R", "B-H")
LOCKED_FOLD_IDS = ("F1", "F2", "F3", "F4", "F5")
REQUIRED_SOURCE_KINDS = (
    "security_master",
    "universe_history",
    "delistings",
    "corporate_actions",
    "daily_market_data",
    "earnings_schedule",
    "benchmark",
    "exchange_calendar",
)
REQUIRED_AS_OF_FACTS = (
    "security_master",
    "universe_history",
    "delistings",
    "corporate_actions",
    "earnings_schedule",
    "benchmark",
    "exchange_calendar",
)

D0 = Decimal(0)
D1 = Decimal(1)


class ContractViolation(ValueError):
    """An ML-v2 setup or point-in-time input failed closed."""


def D(value: Decimal | int | str, name: str = "value") -> Decimal:
    if isinstance(value, (bool, float)):
        raise ContractViolation(f"{name} must be a finite decimal")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractViolation(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ContractViolation(f"{name} must be a finite decimal")
    return result


def _positive(value: Decimal | int | str, name: str) -> Decimal:
    result = D(value, name)
    if result <= 0:
        raise ContractViolation(f"{name} must be positive")
    return result


def _date(value: dt.date, name: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ContractViolation(f"{name} must be a datetime.date")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class SetupContract:
    setup_id: str
    signal_family: str
    ranking: str
    model: Mapping[str, Any]
    eligibility_version: str = "ml-v2-eligibility-v1"
    signal_version: str = "ml-v2-signals-v1"
    feature_schema_version: str = "ml-v2-features-v1"
    execution_version: str = "ml-v2-execution-v1"
    accounting_version: str = "ml-v2-accounting-v1"
    starting_cash: Decimal = Decimal(1000000)
    risk_fraction: Decimal = Decimal("0.005")
    position_fraction: Decimal = Decimal("0.10")
    participation_fraction: Decimal = Decimal("0.01")
    gross_fraction: Decimal = Decimal("0.80")
    max_positions: int = 8
    max_daily_entries: int = 3
    stop_atr_multiple: Decimal = Decimal("1.5")
    target_atr_multiple: Decimal = Decimal("3.0")
    max_stop_fraction: Decimal = Decimal("0.08")
    max_hold_sessions: int = 15
    bps_2x: Decimal = Decimal(10)
    commission_2x: Decimal = Decimal(2)

    @property
    def identity(self) -> str:
        return setup_identity(self)


_MODELS: dict[str, Mapping[str, Any]] = {
    "D": MappingProxyType({"kind": "deterministic", "fit": "none"}),
    "R": MappingProxyType(
        {
            "kind": "ridge",
            "alpha": 10,
            "solver": "lsqr",
            "tol": Decimal("0.000001"),
            "imputation": "fold_median_with_missing_indicators",
            "standardize": True,
        }
    ),
    "H": MappingProxyType(
        {
            "kind": "hist_gradient_boosting",
            "max_leaf_nodes": 15,
            "learning_rate": Decimal("0.05"),
            "max_iter": 200,
            "l2_regularization": 10,
            "min_samples_leaf": 100,
            "early_stopping": False,
        }
    ),
}


def locked_setup_contract(setup_id: str) -> SetupContract:
    normalized = _text(setup_id, "setup_id").upper()
    if normalized not in LOCKED_SETUP_IDS:
        raise ContractViolation(
            f"setup_id must be one of {', '.join(LOCKED_SETUP_IDS)}"
        )
    family, ranking = normalized.split("-")
    return SetupContract(
        setup_id=normalized,
        signal_family=family,
        ranking=ranking,
        model=_MODELS[ranking],
    )


@dataclass(frozen=True)
class SourceRecord:
    kind: str
    content_hash: str
    schema_version: str
    disposition: str = "point_in_time_certified"
    provider: str = "synthetic"
    synthetic: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "source kind"))
        if self.kind not in REQUIRED_SOURCE_KINDS:
            raise ContractViolation(f"unknown source kind {self.kind!r}")
        try:
            require_sha256(self.content_hash, f"{self.kind} content_hash")
        except ValueError as exc:
            raise ContractViolation(str(exc)) from exc
        _text(self.schema_version, f"{self.kind} schema_version")
        if self.disposition != "point_in_time_certified":
            raise ContractViolation(f"{self.kind} is not point-in-time certified")
        if not self.synthetic or self.provider != "synthetic":
            raise ContractViolation("Gate 1 accepts synthetic source records only")


@dataclass(frozen=True)
class PointInTimeManifest:
    authorized_start: dt.date
    authorized_end_exclusive: dt.date
    sources: tuple[SourceRecord, ...]

    def __post_init__(self) -> None:
        start = _date(self.authorized_start, "authorized_start")
        end = _date(self.authorized_end_exclusive, "authorized_end_exclusive")
        if start >= end:
            raise ContractViolation("authorized interval must be non-empty")
        kinds = [source.kind for source in self.sources]
        if len(kinds) != len(set(kinds)):
            raise ContractViolation("source kinds must be unique")
        missing = sorted(set(REQUIRED_SOURCE_KINDS) - set(kinds))
        if missing:
            raise ContractViolation(f"manifest lacks required sources {missing}")
        by_kind = {source.kind: source for source in self.sources}
        object.__setattr__(
            self,
            "sources",
            tuple(by_kind[kind] for kind in REQUIRED_SOURCE_KINDS),
        )

    @property
    def identity(self) -> str:
        return identity_hash("ml-v2/source-manifest/v1", self)


@dataclass(frozen=True)
class Candidate:
    setup_id: str
    fold_id: str
    permanent_id: str
    symbol: str
    signal_session: dt.date
    entry_session: dt.date
    score: Decimal
    signal_close: Decimal
    atr14: Decimal
    mdv20: Decimal
    source_identity: str
    facts_as_of: Mapping[str, dt.date]
    control_values: Mapping[str, Decimal] = field(default_factory=dict)
    signal_to_entry_split_ratio: Decimal = D1
    stale: bool = False

    def __post_init__(self) -> None:
        locked_setup_contract(self.setup_id)
        if self.fold_id not in LOCKED_FOLD_IDS:
            raise ContractViolation(f"fold_id must be one of {LOCKED_FOLD_IDS}")
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        symbol = _text(self.symbol, "symbol").upper()
        if any(character.isspace() for character in symbol):
            raise ContractViolation("symbol cannot contain whitespace")
        object.__setattr__(self, "symbol", symbol)
        signal = _date(self.signal_session, "signal_session")
        entry = _date(self.entry_session, "entry_session")
        if entry <= signal:
            raise ContractViolation("entry_session must follow signal_session")
        object.__setattr__(self, "score", D(self.score, "score"))
        object.__setattr__(self, "signal_close", _positive(self.signal_close, "signal_close"))
        object.__setattr__(self, "atr14", _positive(self.atr14, "atr14"))
        object.__setattr__(self, "mdv20", _positive(self.mdv20, "mdv20"))
        object.__setattr__(
            self,
            "signal_to_entry_split_ratio",
            _positive(self.signal_to_entry_split_ratio, "signal_to_entry_split_ratio"),
        )
        try:
            require_sha256(self.source_identity, "source_identity")
        except ValueError as exc:
            raise ContractViolation(str(exc)) from exc
        facts = dict(self.facts_as_of)
        missing = sorted(set(REQUIRED_AS_OF_FACTS) - set(facts))
        if missing:
            raise ContractViolation(f"candidate lacks as-of facts {missing}")
        for name, value in facts.items():
            fact_date = _date(value, f"facts_as_of[{name}]")
            if fact_date > signal:
                raise ContractViolation(
                    f"future fact {name} at {fact_date} exceeds signal session {signal}"
                )
        object.__setattr__(self, "facts_as_of", MappingProxyType(facts))
        controls = {
            _text(name, "control value name"): D(value, f"control_values[{name}]")
            for name, value in self.control_values.items()
        }
        object.__setattr__(self, "control_values", MappingProxyType(controls))

    def validate_against(self, manifest: PointInTimeManifest) -> None:
        if self.source_identity != manifest.identity:
            raise ContractViolation("candidate source identity does not match manifest")
        if not (
            manifest.authorized_start
            <= self.signal_session
            < manifest.authorized_end_exclusive
        ):
            raise ContractViolation("candidate signal session is outside authorized interval")


@dataclass(frozen=True)
class Bar:
    permanent_id: str
    symbol: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    executable_open: bool = True
    documented_halt: bool = False
    stale: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol").upper())
        values = {
            name: None if value is None else D(value, name)
            for name, value in {
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
            }.items()
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        complete = all(value is not None for value in values.values())
        if complete:
            open_price = values["open"]
            high = values["high"]
            low = values["low"]
            close = values["close"]
            assert open_price is not None and high is not None
            assert low is not None and close is not None
            if min(open_price, high, low, close) < 0:
                raise ContractViolation("OHLC prices cannot be negative")
            if low > high or not low <= open_price <= high or not low <= close <= high:
                raise ContractViolation("bar violates OHLC ordering")
        elif self.executable_open or not self.documented_halt:
            raise ContractViolation(
                "incomplete OHLC requires a documented halt and non-executable open"
            )


@dataclass(frozen=True)
class Split:
    permanent_id: str
    ratio: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        object.__setattr__(self, "ratio", _positive(self.ratio, "split ratio"))


@dataclass(frozen=True)
class CashDistribution:
    permanent_id: str
    amount_per_share: Decimal
    payable_session: dt.date

    def __post_init__(self) -> None:
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        amount = D(self.amount_per_share, "amount_per_share")
        if amount < 0:
            raise ContractViolation("cash distribution cannot be negative")
        object.__setattr__(self, "amount_per_share", amount)
        _date(self.payable_session, "payable_session")


@dataclass(frozen=True)
class Delisting:
    permanent_id: str
    recovery_per_share: Decimal | None
    certified: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "permanent_id", _text(self.permanent_id, "permanent_id"))
        if not self.certified:
            raise ContractViolation("delisting treatment must be certified")
        recovery = (
            None
            if self.recovery_per_share is None
            else D(self.recovery_per_share, "recovery_per_share")
        )
        if recovery is not None and recovery < 0:
            raise ContractViolation("delisting recovery cannot be negative")
        object.__setattr__(self, "recovery_per_share", recovery)


@dataclass(frozen=True)
class SessionFrame:
    session: dt.date
    bars: tuple[Bar, ...]
    splits: tuple[Split, ...] = ()
    distributions: tuple[CashDistribution, ...] = ()
    delistings: tuple[Delisting, ...] = ()

    def __post_init__(self) -> None:
        _date(self.session, "session")
        for name, items in (
            ("bars", self.bars),
            ("splits", self.splits),
            ("distributions", self.distributions),
            ("delistings", self.delistings),
        ):
            ids = [item.permanent_id for item in items]
            if len(ids) != len(set(ids)):
                raise ContractViolation(f"{name} contains duplicate permanent IDs")


def validate_synthetic_inputs(
    *,
    setup: SetupContract,
    manifest: PointInTimeManifest,
    sessions: tuple[SessionFrame, ...],
    candidates: tuple[Candidate, ...],
) -> None:
    if setup != locked_setup_contract(setup.setup_id):
        raise ContractViolation("setup differs from its locked ML-v2 contract")
    dates = [frame.session for frame in sessions]
    if dates != sorted(set(dates)):
        raise ContractViolation(
            "sessions contain a duplicate or are not strictly increasing"
        )
    for candidate in candidates:
        if candidate.setup_id != setup.setup_id:
            raise ContractViolation("candidate setup differs from simulator setup")
        candidate.validate_against(manifest)
        if candidate.entry_session not in set(dates):
            raise ContractViolation("candidate entry session is absent from session frames")
    opportunity_keys = [
        (
            candidate.setup_id,
            candidate.fold_id,
            candidate.permanent_id,
            candidate.signal_session,
            candidate.entry_session,
        )
        for candidate in candidates
    ]
    if len(opportunity_keys) != len(set(opportunity_keys)):
        raise ContractViolation("candidate opportunities contain a duplicate")
    permanent_session_keys = [
        (bar.permanent_id, frame.session)
        for frame in sessions
        for bar in frame.bars
    ]
    if len(permanent_session_keys) != len(set(permanent_session_keys)):
        raise ContractViolation("duplicate (permanent_id, session) market facts")


_SYMBOL_PATTERN = re.compile(r"^\S+$")
