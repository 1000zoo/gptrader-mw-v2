
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

from src.common.model.params import IndParams
from src.indicators.engine.calculator import Calculator

class Indicator:
    def __init__(self, ohlcv: List[Dict], indParams: IndParams = IndParams()):
        self.cal = Calculator(ohlcv=ohlcv)
        self.tail = indParams.tail
        self.params = indParams

    def tuple_tail_list(self, data: Tuple) -> Tuple[List, ...]:
        temp = []
        for d in data:
            temp.append(self.tail_list(d))
        return tuple(temp)

    def tail_list(self, data: pd.Series) -> List:
        return data.tail(self.tail).tolist()

    def timestamp(self) -> List:
        return self.cal.timestamp().tolist()

    def ma_fast(self) -> List:
        return self.tail_list(
            self.cal.cal_ma(window=self.params.ma_fast_w, col=self.params.col)
        )
    
    def ma_slow(self) -> List:
        return self.tail_list(
            self.cal.cal_ma(window=self.params.ma_slow_w, col=self.params.col)
        )

    def ema_fast(self) -> List:
        return self.tail_list(
            self.cal.cal_ema(window=self.params.ema_fast_w, col=self.params.col)
        )

    def ema_slow(self) -> List:
        return self.tail_list(
            self.cal.cal_ema(window=self.params.ema_slow_w, col=self.params.col)
        )

    def rsi(self) -> List:
        return self.tail_list(
            self.cal.rsi(window=self.params.rsi_w, col=self.params.col)
        )
    
    def macd(self) -> Tuple[list, ...]:
        return self.tuple_tail_list(
            self.cal.macd(
                fast=self.params.ema_fast_w,
                slow=self.params.ema_slow_w,
                signal=self.params.macd_signal,
                col=self.params.col
            )
        )
    
    def bollinger(self) -> Tuple[list, ...]:
        return self.tuple_tail_list(
            self.cal.bollinger(
                window=self.params.ma_fast_w,
                k=self.params.bollinger_k,
                col=self.params.col
            )
        )

    def true_range(self) -> List:
        return self.tail_list(self.cal.true_range())
    
    def atr(self, window: int = 14) -> List:
        return self.tail_list(
            self.cal.atr(window=self.params.atr_w)
        )
    
    def dmi_adx(self) -> Tuple[List, ...]:
        return self.tuple_tail_list(
            self.cal.dmi_adx(
                window=self.params.atr_w
            )
        )
    
    def stochastic_kd(self) -> Tuple[List, ...]:
        return self.tuple_tail_list(
            self.cal.stochastic_kd(
                k_period=self.params.kd_k_w,
                d_period=self.params.kd_d_w
            )
        )
    
    def cci(self) -> List:
        return self.tail_list(
            self.cal.cci(window=self.params.ma_slow_w)
        )
    
    def roc(self) -> List:
        return self.tail_list(
            self.cal.roc(window=self.params.roc_w, col=self.params.col)
        )

    def momentum(self) -> List:
        return self.tail_list(
            self.cal.momentum(window=self.params.momentum_w, col=self.params.col)
        )
    
    def obv(self) -> List:
        return self.tail_list(
            self.cal.obv()
        )

    def mfi(self) -> List:
        return self.tail_list(
            self.cal.mfi(window=self.params.mfi_w)
        )

    def vwap(self) -> List:
        return self.tail_list(
            self.cal.vwap()
        )

    def donchian(self) -> Tuple[List, ...]:
        return self.tuple_tail_list(
            self.cal.donchian(
                window=self.params.donchain_w
            )
        )

    def keltner(self) -> Tuple[List, ...]:
        return self.tuple_tail_list(
            self.cal.keltner(
                ema_period=self.params.ema_fast_w,
                atr_period=self.params.atr_w,
                mult=self.params.keltner_m
            )
        )

    def linear_regression_slope(self, col: str = 'low') -> Tuple[List, ...]:
        return self.tuple_tail_list(
            self.cal.linear_regression_slope(
                period=self.params.linear_regression_slope_w,
                col=col
            )
        )
    
    ## def get_all -> tuple 의 경우, 변수 쪼개서
    def get_all(self):
        macd_line, macd_signal_line, macd_hist = self.macd()
        bollinger_mid, bollinger_upper, bollinger_lower, bollinger_width = self.bollinger()
        dmi_plus_di, dmi_minus_di, dmi_adx = self.dmi_adx()
        stochastic_per_k, stochastic_per_d = self.stochastic_kd()
        donchain_upper, donchain_lower = self.donchian()
        keltner_mid, keltner_upper, keltner_lower = self.keltner()
        low_slope, low_direction = self.linear_regression_slope(col='low')
        high_slope, high_direction = self.linear_regression_slope(col='high')

        return {
            "timestamp": self.timestamp(),
            "ma_fast": self.ma_fast(),
            "ma_slow": self.ma_slow(),
            "ema_fast": self.ema_fast(),
            "ema_slow": self.ema_slow(),
            "rsi": self.rsi(),
            "macd_line": macd_line,
            "macd_signal_line": macd_signal_line,
            "macd_hist": macd_hist,
            "bollinger_mid": bollinger_mid,
            "bollinger_upper": bollinger_upper,
            "bollinger_lower": bollinger_lower,
            "bollinger_width": bollinger_width,
            "true_range": self.true_range(),
            "atr": self.atr(),
            "dmi_plus_di": dmi_plus_di,
            "dmi_minus_di": dmi_minus_di,
            "dmi_adx": dmi_adx,
            "stochastic_per_k": stochastic_per_k,
            "stochastic_per_d": stochastic_per_d,
            "cci": self.cci(),
            "roc": self.roc(),
            "momentum": self.momentum(),
            "obv": self.obv(),
            "mfi": self.mfi(),
            "vwap": self.vwap(),
            "donchain_upper": donchain_upper,
            "donchain_lower": donchain_lower,
            "keltner_mid": keltner_mid,
            "keltner_upper": keltner_upper,
            "keltner_lower": keltner_lower,
            "low_linear_regression_slope": low_slope,
            "low_linear_regression_direction": low_direction,
            "high_linear_regression_slope": high_slope,
            "high_linear_regression_direction": high_direction
        }
    
    def getT(self) -> List[Dict]:
        origin = self.get_all()
        
        ret = []
        key_set = origin.keys()

        for i in range(self.tail):
            temp = {}
            for key in key_set:
                temp[key] = origin.get(key)[i]
            ret.append(temp)
        
        return ret