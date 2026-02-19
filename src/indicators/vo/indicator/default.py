from typing import Dict, List, Any

from datetime import datetime
from typing import Optional

from src.common.model.base import Vo

class DefaultIndicatorVo(Vo):
    id: Optional[int] = None

    reg_ymd: Optional[str] = None           # '20251221'
    symbol_id: Optional[str] = None
    batch_id: Optional[str] = None
    indicator_parameter_id: Optional[str] = None

    c_interval: Optional[str] = None
    c_limit: Optional[int] = None
    seq_no: Optional[int] = None
    ts: Optional[datetime] = None

    ma_fast: Optional[float] = None
    ma_slow: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    ema_gap: Optional[float] = None
    ema_gap_ratio: Optional[float] = None
    rsi: Optional[float] = None

    macd_line: Optional[float] = None
    macd_signal_line: Optional[float] = None
    macd_hist: Optional[float] = None

    bollinger_mid: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    bollinger_width: Optional[float] = None

    true_range: Optional[float] = None
    atr: Optional[float] = None

    dmi_plus_di: Optional[float] = None
    dmi_minus_di: Optional[float] = None
    dmi_adx: Optional[float] = None

    stochastic_per_k: Optional[float] = None
    stochastic_per_d: Optional[float] = None

    cci: Optional[float] = None
    roc: Optional[float] = None
    momentum: Optional[float] = None
    obv: Optional[float] = None
    mfi: Optional[float] = None
    vwap: Optional[float] = None

    donchain_upper: Optional[float] = None
    donchain_lower: Optional[float] = None

    keltner_mid: Optional[float] = None
    keltner_upper: Optional[float] = None
    keltner_lower: Optional[float] = None

    low_linear_regression_slope: Optional[float] = None
    low_linear_regression_direction: Optional[float] = None
    high_linear_regression_slope: Optional[float] = None
    high_linear_regression_direction: Optional[float] = None

    class Config:
        from_attributes = True
        extra = "ignore"

    def dump_for_prompt(self) -> Dict[str, Any]:
        ts_val: Optional[datetime] = self.ts
        ts_iso = ts_val.isoformat() if ts_val else None

        return {
            "timestamp": ts_iso,

            "ma_fast": self.ma_fast,
            "ma_slow": self.ma_slow,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_gap": self.ema_gap,
            "ema_gap_ratio": self.ema_gap_ratio,

            "rsi": self.rsi,

            "macd_line": self.macd_line,
            "macd_signal_line": self.macd_signal_line,
            "macd_hist": self.macd_hist,

            "bollinger_mid": self.bollinger_mid,
            "bollinger_upper": self.bollinger_upper,
            "bollinger_lower": self.bollinger_lower,
            "bollinger_width": self.bollinger_width,

            "true_range": self.true_range,
            "atr": self.atr,

            "dmi_plus_di": self.dmi_plus_di,
            "dmi_minus_di": self.dmi_minus_di,
            "dmi_adx": self.dmi_adx,

            "stochastic_per_k": self.stochastic_per_k,
            "stochastic_per_d": self.stochastic_per_d,

            "cci": self.cci,
            "roc": self.roc,
            "momentum": self.momentum,

            "obv": self.obv,
            "mfi": self.mfi,
            "vwap": self.vwap,

            "donchain_upper": self.donchain_upper,
            "donchain_lower": self.donchain_lower,

            "keltner_mid": self.keltner_mid,
            "keltner_upper": self.keltner_upper,
            "keltner_lower": self.keltner_lower,

            "low_linear_regression_slope": self.low_linear_regression_slope,
            "low_linear_regression_direction": self.low_linear_regression_direction,
            "high_linear_regression_slope": self.high_linear_regression_slope,
            "high_linear_regression_direction": self.high_linear_regression_direction,
        }

    @staticmethod
    def to_vo(data: Dict, **meta) -> "DefaultIndicatorVo":
        """
        data: Calculator.getT()에서 나온 단일 row dict
        meta: reg_ymd, symbol_id, batch_id, indicator_parameter_id,
              c_interval, c_limit, seq_no 등
        """
        return DefaultIndicatorVo(
            # ===== meta =====
            reg_ymd=meta.get("reg_ymd"),
            symbol_id=meta.get("symbol_id"),
            batch_id=meta.get("batch_id"),
            indicator_parameter_id=meta.get("indicator_parameter_id"),
            c_interval=meta.get("c_interval"),
            c_limit=meta.get("c_limit"),
            seq_no=meta.get("seq_no"),

            # ===== data =====
            ts=data["timestamp"],

            ma_fast=data.get("ma_fast"),
            ma_slow=data.get("ma_slow"),
            ema_fast=data.get("ema_fast"),
            ema_slow=data.get("ema_slow"),
            ema_gap=data.get("ema_gap"),
            ema_gap_ratio=data.get("ema_gap_ratio"),
            rsi=data.get("rsi"),

            macd_line=data.get("macd_line"),
            macd_signal_line=data.get("macd_signal_line"),
            macd_hist=data.get("macd_hist"),

            bollinger_mid=data.get("bollinger_mid"),
            bollinger_upper=data.get("bollinger_upper"),
            bollinger_lower=data.get("bollinger_lower"),
            bollinger_width=data.get("bollinger_width"),

            true_range=data.get("true_range"),
            atr=data.get("atr"),

            dmi_plus_di=data.get("dmi_plus_di"),
            dmi_minus_di=data.get("dmi_minus_di"),
            dmi_adx=data.get("dmi_adx"),

            stochastic_per_k=data.get("stochastic_per_k"),
            stochastic_per_d=data.get("stochastic_per_d"),

            cci=data.get("cci"),
            roc=data.get("roc"),
            momentum=data.get("momentum"),
            obv=data.get("obv"),
            mfi=data.get("mfi"),
            vwap=data.get("vwap"),

            donchain_upper=data.get("donchain_upper"),
            donchain_lower=data.get("donchain_lower"),

            keltner_mid=data.get("keltner_mid"),
            keltner_upper=data.get("keltner_upper"),
            keltner_lower=data.get("keltner_lower"),

            low_linear_regression_slope=data.get("low_linear_regression_slope"),
            low_linear_regression_direction=data.get("low_linear_regression_direction"),
            high_linear_regression_slope=data.get("high_linear_regression_slope"),
            high_linear_regression_direction=data.get("high_linear_regression_direction"),
        )
