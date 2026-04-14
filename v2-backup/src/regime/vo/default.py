from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from src.common.model.base import Vo


class RegimeScores(BaseModel):
    trend_strength: float = 0.0
    range_strength: float = 0.0
    transition_risk: float = 0.0


class RegimeFeatures(BaseModel):
    adx: Optional[float] = None
    atr: Optional[float] = None
    bb_bandwidth: Optional[float] = None
    ema_gap: Optional[float] = None


class RegimeResult(BaseModel):
    symbol: str
    timeframe: str = "1h"
    regime: str
    scores: RegimeScores
    features: RegimeFeatures
    computed_at: datetime


class DefaultRegimeStateVo(Vo):
    symbol_id: str
    timeframe: str = "1h"
    regime: str = "UNKNOWN"
    pending_regime: Optional[str] = None
    pending_count: int = 0
    trend_strength: float = 0.0
    range_strength: float = 0.0
    transition_risk: float = 0.0
    adx: Optional[float] = None
    atr: Optional[float] = None
    bb_bandwidth: Optional[float] = None
    ema_gap: Optional[float] = None
    computed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        extra = "ignore"
