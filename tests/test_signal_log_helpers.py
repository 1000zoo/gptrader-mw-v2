import pytest

pydantic = pytest.importorskip("pydantic")

from src.analyze.service.openAi.analyze.analyze_service import AnalyzeService


def test_normalize_confidence():
    assert AnalyzeService._normalize_confidence(None) is None
    assert AnalyzeService._normalize_confidence(0.42) == 0.42
    assert AnalyzeService._normalize_confidence(55) == 0.55
