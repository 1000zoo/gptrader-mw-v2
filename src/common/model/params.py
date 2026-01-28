from pydantic import BaseModel

class IndParams(BaseModel):
    name: str = "default"
    tail: int = 30
    col: str = "close"

    ma_fast_w : int = 20
    ma_slow_w : int = 60
    ema_fast_w : int = 20
    ema_slow_w : int = 60
    std_w : int = 20
    rsi_w : int = 14
    macd_signal : int = 9
    bollinger_k : float = 2.0
    atr_w : int = 14
    kd_k_w : int = 14
    kd_d_w : int = 14
    roc_w : int = 14
    momentum_w : int = 14
    mfi_w : int = 14
    donchain_w : int = 20
    keltner_m : float = 2.0
    linear_regression_slope_w : int = 150

    def to_dict(self):
        return {
            "tail": self.tail,
            "col": self.col,
            "ma_fast_w": self.ma_fast_w,
            "ma_slow_w": self.ma_slow_w,
            "ema_fast_w": self.ema_fast_w,
            "ema_slow_w": self.ema_slow_w,
            "std_w": self.std_w,
            "rsi_w": self.rsi_w,
            "macd_signal": self.macd_signal,
            "bollinger_k": self.bollinger_k,
            "atr_w": self.atr_w,
            "kd_k_w": self.kd_k_w,
            "kd_d_w": self.kd_d_w,
            "roc_w": self.roc_w,
            "momentum_w": self.momentum_w,
            "mfi_w": self.mfi_w,
            "donchain_w": self.donchain_w,
            "keltner_m": self.keltner_m,
            "linear_regression_slope_w": self.linear_regression_slope_w,
        }