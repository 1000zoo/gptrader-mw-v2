"""Select a regime model using predeclared, strategy-independent evidence gates."""

from dataclasses import dataclass, field
from math import isfinite


_MODEL_TYPES = ("kmeans", "gmm")


@dataclass(frozen=True)
class RegimeModelEvidence:
    artifact_id: str
    model_type: str
    cluster_fingerprints: tuple[str, ...]
    weekly_episode_counts: tuple[int, ...]
    distinct_calendar_month_counts: tuple[int, ...]
    seed_ari: float
    seed_nmi: float
    matched_centroid_distance: float
    prevalence_drift: float
    low_confidence_rate: float
    silhouette: float | None = None
    bic: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("artifact_id must be nonempty")
        if self.model_type not in _MODEL_TYPES:
            raise ValueError(f"model_type must be one of {_MODEL_TYPES}")
        if not isinstance(self.cluster_fingerprints, tuple) or not self.cluster_fingerprints:
            raise ValueError("cluster_fingerprints must be a nonempty tuple")
        if any(not isinstance(item, str) or not item.strip() for item in self.cluster_fingerprints):
            raise ValueError("cluster fingerprints must be nonempty")
        if len(set(self.cluster_fingerprints)) != len(self.cluster_fingerprints):
            raise ValueError("cluster fingerprints must be unique")

        cluster_count = len(self.cluster_fingerprints)
        _validate_count_vector(self.weekly_episode_counts, cluster_count, "weekly episode counts")
        _validate_count_vector(
            self.distinct_calendar_month_counts,
            cluster_count,
            "distinct calendar month counts",
        )
        _validate_bounded(self.seed_ari, "seed_ari", minimum=0.0, maximum=1.0)
        _validate_bounded(self.seed_nmi, "seed_nmi", minimum=0.0, maximum=1.0)
        _validate_bounded(
            self.matched_centroid_distance,
            "matched_centroid_distance",
            minimum=0.0,
        )
        _validate_bounded(self.prevalence_drift, "prevalence_drift", minimum=0.0, maximum=1.0)
        _validate_bounded(
            self.low_confidence_rate,
            "low_confidence_rate",
            minimum=0.0,
            maximum=1.0,
        )
        if self.silhouette is not None:
            _validate_bounded(self.silhouette, "silhouette", minimum=-1.0, maximum=1.0)
        if self.bic is not None:
            _validate_finite_number(self.bic, "bic")


@dataclass(frozen=True)
class RegimeModelGateThresholds:
    minimum_weekly_episodes: int = 8
    minimum_distinct_months: int = 3
    minimum_seed_ari: float = 0.8
    minimum_seed_nmi: float = 0.8
    maximum_matched_centroid_distance: float = 0.5
    maximum_prevalence_drift: float = 0.2
    maximum_low_confidence_rate: float = 0.25

    def __post_init__(self) -> None:
        _validate_nonnegative_int(self.minimum_weekly_episodes, "minimum_weekly_episodes")
        _validate_nonnegative_int(self.minimum_distinct_months, "minimum_distinct_months")
        _validate_bounded(self.minimum_seed_ari, "minimum_seed_ari", minimum=0.0, maximum=1.0)
        _validate_bounded(self.minimum_seed_nmi, "minimum_seed_nmi", minimum=0.0, maximum=1.0)
        _validate_bounded(
            self.maximum_matched_centroid_distance,
            "maximum_matched_centroid_distance",
            minimum=0.0,
        )
        _validate_bounded(
            self.maximum_prevalence_drift,
            "maximum_prevalence_drift",
            minimum=0.0,
            maximum=1.0,
        )
        _validate_bounded(
            self.maximum_low_confidence_rate,
            "maximum_low_confidence_rate",
            minimum=0.0,
            maximum=1.0,
        )


@dataclass(frozen=True)
class SelectRegimeModelCommand:
    candidates: tuple[RegimeModelEvidence, ...]
    thresholds: RegimeModelGateThresholds = field(default_factory=RegimeModelGateThresholds)
    model_family_priority: tuple[str, ...] = _MODEL_TYPES

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple):
            raise ValueError("candidates must be a tuple")
        if any(not isinstance(candidate, RegimeModelEvidence) for candidate in self.candidates):
            raise ValueError("candidates must contain RegimeModelEvidence")
        artifact_ids = tuple(candidate.artifact_id for candidate in self.candidates)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("candidate artifact IDs must be unique")
        if not isinstance(self.thresholds, RegimeModelGateThresholds):
            raise ValueError("thresholds must be RegimeModelGateThresholds")
        if (
            not isinstance(self.model_family_priority, tuple)
            or len(self.model_family_priority) != len(_MODEL_TYPES)
            or set(self.model_family_priority) != set(_MODEL_TYPES)
        ):
            raise ValueError(f"model family priority must be a permutation of {_MODEL_TYPES}")


@dataclass(frozen=True)
class RegimeModelCandidateDecision:
    artifact_id: str
    model_type: str
    eligible: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class SelectRegimeModelResult:
    selected_artifact_id: str | None
    decisions: tuple[RegimeModelCandidateDecision, ...]
    family_winners: tuple[tuple[str, str], ...]
    model_family_priority: tuple[str, ...]


class SelectRegimeModelUseCase:
    def execute(self, command: SelectRegimeModelCommand) -> SelectRegimeModelResult:
        ordered_candidates = tuple(sorted(command.candidates, key=lambda item: item.artifact_id))
        decisions = tuple(
            _apply_gates(candidate, command.thresholds) for candidate in ordered_candidates
        )
        eligible_ids = {
            decision.artifact_id for decision in decisions if decision.eligible
        }
        candidates_by_id = {candidate.artifact_id: candidate for candidate in ordered_candidates}

        family_winners: list[tuple[str, str]] = []
        for family in command.model_family_priority:
            family_candidates = [
                candidates_by_id[artifact_id]
                for artifact_id in eligible_ids
                if candidates_by_id[artifact_id].model_type == family
            ]
            if not family_candidates:
                continue
            if family == "kmeans":
                winner = min(
                    family_candidates,
                    key=lambda item: (-_required_silhouette(item), item.artifact_id),
                )
            else:
                winner = min(
                    family_candidates,
                    key=lambda item: (_required_bic(item), item.artifact_id),
                )
            family_winners.append((family, winner.artifact_id))

        selected_artifact_id = family_winners[0][1] if family_winners else None
        return SelectRegimeModelResult(
            selected_artifact_id=selected_artifact_id,
            decisions=decisions,
            family_winners=tuple(family_winners),
            model_family_priority=command.model_family_priority,
        )


def select_model(command: SelectRegimeModelCommand) -> SelectRegimeModelResult:
    """Functional entry point for callers that do not need an injected use-case object."""

    return SelectRegimeModelUseCase().execute(command)


def _apply_gates(
    candidate: RegimeModelEvidence,
    thresholds: RegimeModelGateThresholds,
) -> RegimeModelCandidateDecision:
    reasons: list[str] = []
    if any(count < thresholds.minimum_weekly_episodes for count in candidate.weekly_episode_counts):
        reasons.append("minimum_weekly_episodes")
    if any(
        count < thresholds.minimum_distinct_months
        for count in candidate.distinct_calendar_month_counts
    ):
        reasons.append("minimum_distinct_months")
    if (
        candidate.seed_ari < thresholds.minimum_seed_ari
        or candidate.seed_nmi < thresholds.minimum_seed_nmi
    ):
        reasons.append("seed_stability")
    if candidate.matched_centroid_distance > thresholds.maximum_matched_centroid_distance:
        reasons.append("centroid_stability")
    if candidate.prevalence_drift > thresholds.maximum_prevalence_drift:
        reasons.append("prevalence_drift")
    if candidate.low_confidence_rate > thresholds.maximum_low_confidence_rate:
        reasons.append("low_confidence_rate")
    if not _has_valid_family_metric(candidate):
        reasons.append("family_metric_validity")
    return RegimeModelCandidateDecision(
        artifact_id=candidate.artifact_id,
        model_type=candidate.model_type,
        eligible=not reasons,
        rejection_reasons=tuple(reasons),
    )


def _has_valid_family_metric(candidate: RegimeModelEvidence) -> bool:
    if candidate.model_type == "kmeans":
        return candidate.silhouette is not None and candidate.bic is None
    return candidate.bic is not None and candidate.silhouette is None


def _required_silhouette(candidate: RegimeModelEvidence) -> float:
    if candidate.silhouette is None:  # pragma: no cover - guarded by eligibility
        raise ValueError("eligible KMeans candidate lacks silhouette")
    return candidate.silhouette


def _required_bic(candidate: RegimeModelEvidence) -> float:
    if candidate.bic is None:  # pragma: no cover - guarded by eligibility
        raise ValueError("eligible GMM candidate lacks BIC")
    return candidate.bic


def _validate_count_vector(values: tuple[int, ...], expected_size: int, label: str) -> None:
    if not isinstance(values, tuple) or len(values) != expected_size:
        raise ValueError(f"{label} must represent every cluster")
    for value in values:
        _validate_nonnegative_int(value, label)


def _validate_nonnegative_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must contain nonnegative integers")


def _validate_finite_number(value: float, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} must be finite")


def _validate_bounded(
    value: float,
    label: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> None:
    _validate_finite_number(value, label)
    if value < minimum or (maximum is not None and value > maximum):
        qualifier = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise ValueError(f"{label} must be{qualifier}")


__all__ = [
    "RegimeModelCandidateDecision",
    "RegimeModelEvidence",
    "RegimeModelGateThresholds",
    "SelectRegimeModelCommand",
    "SelectRegimeModelResult",
    "SelectRegimeModelUseCase",
    "select_model",
]
