from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultSignalLogVo(Vo):
    id: Optional[int] = None
    run_id: Optional[str] = None
    job_run_id: Optional[str] = None
    symbol_id: Optional[str] = None
    c_interval: Optional[str] = None
    base_ts: Optional[datetime] = None
    window_start_ts: Optional[datetime] = None
    window_end_ts: Optional[datetime] = None
    n_candles: Optional[int] = None
    indicator_params_version: Optional[str] = None
    prompt_version: Optional[str] = None
    model_name: Optional[str] = None
    model_temperature: Optional[float] = None
    raw_position: Optional[str] = None
    raw_confidence: Optional[float] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    rationale: Optional[str] = None
    gate_allowed: Optional[bool] = None
    gate_rejected_reason: Optional[str] = None
    calibrated_confidence: Optional[float] = None
    dynamic_threshold_used: Optional[float] = None
    final_action: Optional[str] = None
    replay_status: Optional[str] = None
    analyze_result_id: Optional[int] = None
    analyze_action_id: Optional[int] = None

    class Config:
        from_attributes = True
        extra = "ignore"
