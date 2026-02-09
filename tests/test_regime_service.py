from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pandas")

from src.regime.service.regime_service import (
    DOWNTREND,
    RANGE,
    TRANSITION,
    UNKNOWN,
    UPTREND,
    RegimeService,
)


def _build_klines(prices: np.ndarray):
    rows = []
    for i, close in enumerate(prices):
        open_px = prices[i - 1] if i > 0 else close
        high = max(open_px, close) * 1.002
        low = min(open_px, close) * 0.998
        rows.append(
            {
                "openTime": f"2026-01-01 00:{i:02d}:00",
                "open": float(open_px),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "quoteAssetVolume": 1000.0,
            }
        )
    return rows


def test_regime_uptrend():
    service = RegimeService()
    k1h = _build_klines(np.linspace(100, 200, 220))
    k15m = _build_klines(np.linspace(100, 210, 420))
    result = service.classify_regime("BTCUSDT", k1h, k15m, computed_at=datetime.now(timezone.utc))
    assert result.regime == UPTREND


def test_regime_downtrend():
    service = RegimeService()
    k1h = _build_klines(np.linspace(200, 100, 220))
    k15m = _build_klines(np.linspace(210, 100, 420))
    result = service.classify_regime("BTCUSDT", k1h, k15m, computed_at=datetime.now(timezone.utc))
    assert result.regime == DOWNTREND


def test_regime_range():
    service = RegimeService()
    rng = np.random.default_rng(0)
    base_1h = np.concatenate([100 + rng.normal(0, 0.2, 190), np.full(30, 100.0)])
    base_15m = np.concatenate([100 + rng.normal(0, 0.15, 380), np.full(40, 100.0)])
    k1h = _build_klines(base_1h)
    k15m = _build_klines(base_15m)
    result = service.classify_regime("BTCUSDT", k1h, k15m, computed_at=datetime.now(timezone.utc))
    assert result.regime == RANGE


def test_regime_transition_by_spike():
    service = RegimeService()
    base_1h = np.linspace(100, 105, 220)
    base_15m = np.concatenate([np.linspace(100, 101, 419), np.array([120.0])])
    k1h = _build_klines(base_1h)
    k15m = _build_klines(base_15m)
    result = service.classify_regime("BTCUSDT", k1h, k15m, computed_at=datetime.now(timezone.utc))
    assert result.regime == TRANSITION


def test_regime_unknown_when_data_short():
    service = RegimeService()
    k1h = _build_klines(np.linspace(100, 120, 50))
    k15m = _build_klines(np.linspace(100, 120, 100))
    result = service.classify_regime("BTCUSDT", k1h, k15m, computed_at=datetime.now(timezone.utc))
    assert result.regime == UNKNOWN
