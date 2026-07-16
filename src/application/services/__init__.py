"""Reusable application services.

Daily evidence names are resolved lazily because the canonical research replay
imports the chart-feature service while it is being initialized.
"""
from src.application.services.three_day_chart_feature_extractor import (
    calculate_three_day_registry_values,
    extract_three_day_chart_feature_vector,
)


__all__ = [
    "AppendOnlyEvidenceLedger",
    "DailyEvidenceRunIdentity",
    "ThreeDayDailyCandidateManifest",
    "build_three_day_daily_candidate_manifest",
    "calculate_three_day_registry_values",
    "extract_three_day_chart_feature_vector",
    "run_daily_strategy_evidence",
]


def __getattr__(name: str):
    if name in {
        "AppendOnlyEvidenceLedger",
        "DailyEvidenceRunIdentity",
        "ThreeDayDailyCandidateManifest",
        "build_three_day_daily_candidate_manifest",
        "run_daily_strategy_evidence",
    }:
        from src.application.services import daily_strategy_evidence

        return getattr(daily_strategy_evidence, name)
    raise AttributeError(name)
