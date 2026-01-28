import asyncio

import pytest

pytest.importorskip("loguru")

from src.calibration.calibration_service import CalibrationService, BucketStat


def test_calibration_bucket_stats(monkeypatch):
    service = CalibrationService()

    async def fake_fetch(c_interval, symbol_id=None):
        return [
            {"raw_confidence": 0.15, "pnl_usd": 5, "r_multiple": 1.0},
            {"raw_confidence": 0.15, "pnl_usd": -2, "r_multiple": -0.5},
            {"raw_confidence": 0.85, "pnl_usd": 3, "r_multiple": 0.3},
        ]

    monkeypatch.setattr(service.repo, "fetch_trade_outcomes", fake_fetch)
    stats = asyncio.run(service.compute_bucket_stats("1h"))
    bucket = next(s for s in stats if s.bucket_from == 0.1)
    assert bucket.trades == 2
    assert bucket.winrate == 0.5


def test_dynamic_threshold_selection():
    stats = [
        BucketStat(0.0, 0.1, 10, 0.5, -0.1, -0.1, 0.0),
        BucketStat(0.1, 0.2, 30, 0.6, 0.2, 0.2, 1.5),
    ]
    threshold = CalibrationService.select_dynamic_threshold(stats, min_trades=30)
    assert threshold == 0.1
