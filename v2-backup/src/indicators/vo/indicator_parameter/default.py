from typing import Optional

from src.common.model.base import Vo

class DefaultIndicatorParamsVo(Vo):
    name: str
    tail: Optional[int] = None
    col: Optional[str] = None

    ma_fast_w: Optional[int] = None
    ma_slow_w: Optional[int] = None
    ema_fast_w: Optional[int] = None
    ema_slow_w: Optional[int] = None
    std_w: Optional[int] = None
    rsi_w: Optional[int] = None
    macd_signal: Optional[int] = None
    bollinger_k: Optional[float] = None
    atr_w: Optional[int] = None
    kd_k_w: Optional[int] = None
    kd_d_w: Optional[int] = None
    roc_w: Optional[int] = None
    momentum_w: Optional[int] = None
    mfi_w: Optional[int] = None
    donchain_w: Optional[int] = None
    keltner_m: Optional[float] = None
    linear_regression_slope_w: Optional[int] = None

    class Config:
        from_attributes = True
        extra = "ignore"