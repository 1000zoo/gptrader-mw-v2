from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import math
from types import SimpleNamespace

import pytest

from src.application.usecases.regime.select_daily_strategy_usecase import (
    DailySelectStrategyCommand,
    DailySelectStrategyResult,
    SelectDailyStrategyUseCase,
)
from src.domain.market.candle import Candle
from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe
from src.domain.regime.daily_mapping import (
    DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
    DailyCandidateAssessment,
    DailyStrategyMappingArtifact,
    DailyStrategyMappingEntry,
)
from src.domain.regime.mapping import candidate_universe_hash
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import RegimeSelectionState, SelectionEventType
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.domain.regime.three_day_daily_profile import (
    PROFILE_ID,
    STRICT_RISK_POLICY,
    ThreeDayDailyWalkForwardFold,
)


UTC = timezone.utc
BOUNDARY = datetime(2026, 4, 6, tzinfo=UTC)
COMPONENTS = tuple(f"component-{letter}" for letter in "abcd")
CANDIDATES = ("candidate-a", "candidate-b")
MODEL_HASH = hashlib.sha256(b"model").hexdigest()


class _EquivalentUtc(timezone.__base__):
    def utcoffset(self, value):
        return timedelta(0)

    def dst(self, value):
        return timedelta(0)

    def tzname(self, value):
        return "UTC"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _assessment(component: str, candidate: str, eligible: bool) -> DailyCandidateAssessment:
    return DailyCandidateAssessment(
        component_fingerprint=component,
        candidate_id=candidate,
        candidate_hash=_hash(candidate),
        assigned_day_count=40,
        episode_count=35,
        unavailable_day_count=5,
        unavailable_reason_counts=(("feature_unavailable", 5),),
        calendar_month_count=4,
        closed_trade_count=40,
        mean_daily_return_ratio=Decimal("0.003"),
        median_daily_return_ratio=Decimal("0.002"),
        corrected_lower_bound_ratio=Decimal("0.001"),
        worst_seven_day_return_ratio=Decimal("-0.02"),
        expected_shortfall_10_ratio=Decimal("-0.005"),
        maximum_drawdown_ratio=Decimal("0.05"),
        return_without_best_episode_ratio=Decimal("0.03"),
        top_episode_profit_share=Decimal("0.20"),
        top_five_trade_profit_share=Decimal("0.40"),
        eligible=eligible,
        rejection_reasons=() if eligible else ("not_eligible",),
    )


def _mapping(*, entries=None, model_hash=MODEL_HASH) -> DailyStrategyMappingArtifact:
    if entries is None:
        entries = (
            DailyStrategyMappingEntry(COMPONENTS[0], "strategy", CANDIDATES[0]),
            DailyStrategyMappingEntry(COMPONENTS[1], "strategy", CANDIDATES[0]),
            DailyStrategyMappingEntry(COMPONENTS[2], "cash", None, ("no_eligible_candidate",)),
            DailyStrategyMappingEntry(COMPONENTS[3], "strategy", CANDIDATES[1]),
        )
    eligible = {
        (entry.component_fingerprint, entry.strategy_candidate_id)
        for entry in entries
        if entry.decision == "strategy"
    }
    fold = ThreeDayDailyWalkForwardFold.default()
    return DailyStrategyMappingArtifact(
        artifact_version=DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
        profile_id=PROFILE_ID,
        feature_schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        model_artifact_hash=model_hash,
        candidate_universe_hash=candidate_universe_hash(CANDIDATES),
        candidate_ids=CANDIDATES,
        candidate_hashes={candidate: _hash(candidate) for candidate in CANDIDATES},
        component_fingerprints=COMPONENTS,
        entries=entries,
        candidate_assessments=tuple(
            _assessment(component, candidate, (component, candidate) in eligible)
            for component in COMPONENTS
            for candidate in CANDIDATES
        ),
        risk_policy=STRICT_RISK_POLICY,
        cluster_fit=fold.cluster_fit,
        mapping_fit=fold.mapping_fit,
    )


@dataclass(frozen=True)
class _FrozenModel:
    assignment: ClusterAssignment
    artifact_hash: str = MODEL_HASH
    symbol: str = "BTCUSDT"
    profile_id: str = PROFILE_ID
    feature_schema_version: str = THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    component_fingerprints: tuple[str, ...] = COMPONENTS
    feature_names: tuple[str, ...] = ("return_4h", "rv_4h", "atr_ratio_1d", "directional_efficiency_1d")
    assignment_confidence_policy: str = "gmm_top_two_posterior_and_chi_square_distance_v2"
    model_gates: object = None
    calls: object = None

    def __post_init__(self):
        if self.model_gates is None:
            object.__setattr__(self, "model_gates", {
                "gmm_probability_threshold": 0.65,
                "gmm_margin_threshold": 0.10,
                "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
                "distance_threshold": 14.860259000560243,
                "distance_result": True,
                "distance_exceedance_rate": 0.01,
                "maximum_distance_exceedance_rate_threshold": 0.02,
                "passed": True,
            })
        if self.calls is None:
            object.__setattr__(self, "calls", [])

    def assign(self, vector):
        self.calls.append(vector)
        return self.assignment


def _candles(*, count=4320, start=None, symbol=Symbol("BTC", "USDT"), timeframe=Timeframe(1, "m")):
    start = start or BOUNDARY - timedelta(days=3)
    result = []
    previous = Decimal("100")
    for index in range(count):
        opened = start + timedelta(minutes=index)
        close = previous + (Decimal("0.03") if index % 5 else Decimal("-0.02"))
        result.append(Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=opened,
            closed_at=opened + timedelta(seconds=timeframe.duration_seconds),
            open_price=previous,
            high_price=max(previous, close) + Decimal("0.04"),
            low_price=min(previous, close) - Decimal("0.04"),
            close_price=close,
            volume=Decimal(10 + index % 17),
        ))
        previous = close
    return tuple(result)


def _command(*, model=None, mapping=None, candles=None, previous=None, boundary=BOUNDARY):
    return DailySelectStrategyCommand(
        previous_state=previous,
        symbol="BTCUSDT",
        boundary_at=boundary,
        model_artifact=model or _FrozenModel(ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)),
        mapping_artifact=mapping or _mapping(),
        candles=_candles() if candles is None else candles,
    )


@pytest.mark.parametrize("boundary", [
    BOUNDARY.replace(hour=1),
    BOUNDARY.replace(second=1),
    BOUNDARY.replace(microsecond=1),
    BOUNDARY.replace(tzinfo=_EquivalentUtc()),
    BOUNDARY.replace(tzinfo=None),
])
def test_command_accepts_only_exact_canonical_utc_midnight(boundary) -> None:
    with pytest.raises(ValueError, match="midnight UTC"):
        _command(boundary=boundary)


@pytest.mark.parametrize("mutation", ["count", "gap", "order", "symbol", "timeframe", "at-boundary"])
def test_incomplete_or_contaminated_history_fails_closed(mutation) -> None:
    candles = list(_candles())
    if mutation == "count":
        candles.pop()
    elif mutation == "gap":
        candles.pop(100)
    elif mutation == "order":
        candles[100], candles[101] = candles[101], candles[100]
    elif mutation == "symbol":
        candles[100] = replace(candles[100], symbol=Symbol("ETH", "USDT"))
    elif mutation == "timeframe":
        candles[100] = replace(
            candles[100], timeframe=Timeframe(5, "m"),
            closed_at=candles[100].opened_at + timedelta(minutes=5),
        )
    else:
        candles = list(_candles(start=BOUNDARY - timedelta(days=3) + timedelta(minutes=1)))

    result = SelectDailyStrategyUseCase().execute(_command(candles=tuple(candles)))

    assert result.state.active_strategy_profile_id is None
    assert not result.state.new_entries_enabled
    assert result.audit.status == "fail_closed"
    assert "history" in result.audit.reason


def test_assigns_exact_extracted_vector_once_and_activates_first_candidate_immediately() -> None:
    model = _FrozenModel(ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0))

    result = SelectDailyStrategyUseCase().execute(_command(model=model))

    assert isinstance(result, DailySelectStrategyResult)
    assert len(model.calls) == 1
    assert model.calls[0].anchor_at == BOUNDARY
    assert tuple(model.calls[0].values) == tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert result.state.active_strategy_profile_id == CANDIDATES[0]
    assert result.state.new_entries_enabled
    assert result.state.pending_cluster_fingerprint is None
    assert result.state.pending_confirmation_count == 0
    assert result.audit.status == "selected"
    assert result.audit.candidate_definition_hash == _hash(CANDIDATES[0])
    assert len(result.audit.profile_hash) == 64


def test_explicit_cash_mapping_is_immediate_and_audited() -> None:
    model = _FrozenModel(ClusterAssignment(COMPONENTS[2], 0.9, 0.05, 1.0))
    result = SelectDailyStrategyUseCase().execute(_command(model=model))
    assert result.state.active_strategy_profile_id is None
    assert not result.state.new_entries_enabled
    assert result.audit.status == "cash"
    assert "no_eligible_candidate" in result.audit.reason


@pytest.mark.parametrize("case", ["low-probability", "low-margin", "unknown", "model-hash"])
def test_invalid_or_incompatible_selection_fails_closed_with_readable_audit(case) -> None:
    assignment = ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
    mapping = _mapping()
    if case == "low-probability":
        assignment = ClusterAssignment(COMPONENTS[0], 0.64, 0.20, 1.0)
    elif case == "low-margin":
        assignment = ClusterAssignment(COMPONENTS[0], 0.51, 0.49, 1.0)
    elif case == "unknown":
        assignment = ClusterAssignment("unknown-component", 0.9, 0.05, 1.0)
    else:
        mapping = _mapping(model_hash=_hash("other-model"))
    result = SelectDailyStrategyUseCase().execute(
        _command(model=_FrozenModel(assignment), mapping=mapping)
    )
    assert result.audit.status == "fail_closed"
    assert result.audit.reason
    assert result.audit.selection_input_hash == result.selection_input_hash
    assert result.state.active_strategy_profile_id is None
    assert not result.state.new_entries_enabled


def test_same_candidate_component_change_records_only_component_transition() -> None:
    first = SelectDailyStrategyUseCase().execute(_command())
    second = SelectDailyStrategyUseCase().execute(_command(
        previous=first.state,
        boundary=BOUNDARY + timedelta(days=1),
        candles=_candles(start=BOUNDARY - timedelta(days=2)),
        model=_FrozenModel(ClusterAssignment(COMPONENTS[1], 0.9, 0.05, 1.0)),
    ))
    assert second.state.active_strategy_profile_id == CANDIDATES[0]
    assert second.events == (SelectionEventType.CLUSTER_TRANSITION,)
    assert second.audit.previous_component_fingerprint == COMPONENTS[0]
    assert second.audit.previous_candidate_id == CANDIDATES[0]


def test_candidate_and_cash_transitions_record_previous_and_current() -> None:
    first = SelectDailyStrategyUseCase().execute(_command())
    changed = SelectDailyStrategyUseCase().execute(_command(
        previous=first.state, boundary=BOUNDARY + timedelta(days=1),
        candles=_candles(start=BOUNDARY - timedelta(days=2)),
        model=_FrozenModel(ClusterAssignment(COMPONENTS[3], 0.9, 0.05, 1.0)),
    ))
    assert changed.events == (
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.STRATEGY_TRANSITION,
    )
    assert changed.audit.previous_candidate_id == CANDIDATES[0]
    assert changed.audit.candidate_id == CANDIDATES[1]
    cash = SelectDailyStrategyUseCase().execute(_command(
        previous=changed.state, boundary=BOUNDARY + timedelta(days=2),
        candles=_candles(start=BOUNDARY - timedelta(days=1)),
        model=_FrozenModel(ClusterAssignment(COMPONENTS[2], 0.9, 0.05, 1.0)),
    ))
    assert cash.events == (
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.CASH_TRANSITION,
    )
    assert cash.audit.previous_candidate_id == CANDIDATES[1]
    assert cash.audit.candidate_id is None


def test_equal_or_stale_boundary_is_rejected() -> None:
    first = SelectDailyStrategyUseCase().execute(_command())
    with pytest.raises(ValueError, match="boundary"):
        SelectDailyStrategyUseCase().execute(_command(previous=first.state, boundary=BOUNDARY))
    with pytest.raises(ValueError, match="boundary"):
        _command(previous=first.state, boundary=BOUNDARY - timedelta(days=1))


def test_model_and_mapping_snapshot_is_captured_once_before_assignment() -> None:
    class ReplacingModel:
        artifact_hash = MODEL_HASH
        symbol = "BTCUSDT"
        profile_id = PROFILE_ID
        feature_schema_version = THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
        component_fingerprints = COMPONENTS
        feature_names = ("return_4h", "rv_4h", "atr_ratio_1d", "directional_efficiency_1d")
        assignment_confidence_policy = "gmm_top_two_posterior_and_chi_square_distance_v2"
        model_gates = {
            "gmm_probability_threshold": 0.65,
            "gmm_margin_threshold": 0.10,
            "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
            "distance_threshold": 14.860259000560243,
            "distance_result": True,
            "distance_exceedance_rate": 0.01,
            "maximum_distance_exceedance_rate_threshold": 0.02,
            "passed": True,
        }

        def assign(self, vector):
            self.artifact_hash = _hash("replacement")
            self.model_gates = {
                "gmm_probability_threshold": 0.99,
                "gmm_margin_threshold": 0.99,
                "passed": False,
            }
            return ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)

    model = ReplacingModel()
    command = _command(model=model)
    result = SelectDailyStrategyUseCase().execute(command)

    assert result.audit.status == "selected"
    assert result.audit.model_artifact_hash == MODEL_HASH
    assert result.evaluated_artifact_identity == command.artifact_snapshot.artifact_identity


@pytest.mark.parametrize(
    ("distance", "reason"),
    [
        (None, "missing"),
        (14.860259000560244, "exceeds"),
        (float("nan"), "finite"),
        (-1.0, "nonnegative"),
    ],
)
def test_distance_confidence_failures_commit_cash_with_distinct_reason(distance, reason) -> None:
    assignment = (
        ClusterAssignment(COMPONENTS[0], 0.9, 0.05, distance)
        if distance is None or (math.isfinite(distance) and distance >= 0)
        else SimpleNamespace(
            fingerprint=COMPONENTS[0],
            dominant_probability=0.9,
            second_probability=0.05,
            distance=distance,
        )
    )
    result = SelectDailyStrategyUseCase().execute(
        _command(model=_FrozenModel(assignment))
    )
    assert result.audit.status == "fail_closed"
    assert reason in result.audit.reason
    assert result.state.active_strategy_profile_id is None


def test_distance_exact_threshold_passes() -> None:
    result = SelectDailyStrategyUseCase().execute(
        _command(
            model=_FrozenModel(
                ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 14.860259000560243)
            )
        )
    )
    assert result.audit.status == "selected"


@pytest.mark.parametrize("change", ["policy", "gate"])
def test_distance_policy_or_failed_model_gate_is_incompatible(change) -> None:
    gates = dict(_FrozenModel(ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)).model_gates)
    if change == "policy":
        gates["distance_threshold_policy"] = "unsupported"
    else:
        gates["distance_result"] = False
    result = SelectDailyStrategyUseCase().execute(
        _command(
            model=_FrozenModel(
                ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0),
                model_gates=gates,
            )
        )
    )
    assert result.audit.status == "fail_closed"
    assert "incompatible" in result.audit.reason


def test_runtime_model_error_transitions_prior_candidate_to_cash_without_message_leak() -> None:
    first = SelectDailyStrategyUseCase().execute(_command())

    class BrokenModel(_FrozenModel):
        def assign(self, vector):
            raise RuntimeError("api key and unstable details must not leak")

    result = SelectDailyStrategyUseCase().execute(
        _command(
            previous=first.state,
            boundary=BOUNDARY + timedelta(days=1),
            candles=_candles(start=BOUNDARY - timedelta(days=2)),
            model=BrokenModel(ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)),
        )
    )

    assert result.audit.reason == "model_assignment_error:RuntimeError"
    assert result.state.active_strategy_profile_id is None
    assert not result.state.new_entries_enabled
    assert SelectionEventType.CASH_TRANSITION in result.events


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_model_base_exceptions_propagate(error) -> None:
    class InterruptedModel(_FrozenModel):
        def assign(self, vector):
            raise error

    with pytest.raises(type(error)):
        SelectDailyStrategyUseCase().execute(
            _command(
                model=InterruptedModel(
                    ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
                )
            )
        )
