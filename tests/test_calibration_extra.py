import pytest

pytest.importorskip("loguru")

from src.calibration.calibration_service import CalibrationService, BucketStat


def test_calibration_apply_ev():
    stats = [BucketStat(0.0, 0.1, 10, 0.5, 0.2, 0.2, 1.0)]
    calibrated = CalibrationService.calibrate(0.05, stats)
    assert calibrated > 0.05
