import numpy as np
import pandas as pd

from typing import List, Dict, Tuple, Optional

class Calculator:
    def __init__(self, ohlcv: List[Dict]):
        self.df = pd.DataFrame(ohlcv)

        float_cols = ["open", "high", "low", "close", "quoteAssetVolume", 
                      "takerBuyBaseAsset", "takerBuyQuoteAsset"]
        int_cols = ["numberOfTrades"]

        for col in float_cols:
            if col in self.df.columns:
                self.df[col] = self.df[col].astype(float)

        for col in int_cols:
            if col in self.df.columns:
                self.df[col] = self.df[col].astype(int)

        self.df.set_index("openTime", inplace=True)

    def timestamp(self) -> pd.Series:
        return self.df.index

    def series(self, col: str) -> pd.Series:
        return self.df[col]

    def cal_ma(self, window: int = 20, col: str = "close") -> pd.Series:
        return self.df[col].rolling(window=window).mean()

    def cal_ema(self, window: int = 20, col: str = "close", adjust=False) -> pd.Series:
        return self.df[col]\
            .ewm(span=window, adjust=adjust, min_periods=window)\
            .mean()
    
    def std(self, window: int = 20, ddof: int = 0, col: str = "close"):
        return self.df[col].rolling(window=window, min_periods=window).std(ddof=0)

    def rsi(self, window: int = 14, col: str = "close", adjust=False) -> pd.Series:
        series = self.df[col]
        delta = series.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1/window, min_periods=window, adjust=adjust).mean()
        avg_loss = loss.ewm(alpha=1/window, min_periods=window, adjust=adjust).mean()
        rs = avg_gain / (avg_loss.replace(0, np.nan))
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(0.0)
    
    def macd(self,
            fast: int = 12,
            slow: int = 26,
            signal: int = 9,
            col: str = "close") -> Tuple[pd.Series, pd.Series, pd.Series]:
        
        ema_fast = self.cal_ema(window=fast, col=col)
        ema_slow = self.cal_ema(window=slow, col=col)
        signal_line = self.cal_ema(window=signal, col=col)
        macd_line = ema_fast - ema_slow
        hist = macd_line - signal_line
        return macd_line, signal_line, hist
    
    def bollinger(self, 
                window: int = 20,
                k: float = 2.0,
                col: str = "close") -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        mid = self.cal_ma(window=window, col=col)
        std = self.std(window=window, ddof=0, col=col)
        upper = mid + k * std
        lower = mid - k * std
        width = (upper - lower) / mid
        return mid, upper, lower, width

    def true_range(self) -> pd.Series:
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]
        prev_close = close.shift(1)

        return pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
    
    def atr(self, window: int = 14) -> pd.Series:
        return self.true_range()\
                    .ewm(alpha=1/window, adjust=False, min_periods=window)\
                    .mean()
    
    def dmi_adx(self, window: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        high = self.df["high"]
        low = self.df["low"]

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        atr_series = self.atr(window=window)

        plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1/window, adjust=False, min_periods=window).mean() / atr_series
        minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1/window, adjust=False, min_periods=window).mean() / atr_series

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/window, adjust=False, min_periods=window).mean()
        return plus_di.fillna(0.0), minus_di.fillna(0.0), adx.fillna(0.0)
    
    def stochastic_kd(self, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]

        lowest_low = low.rolling(k_period, min_periods=k_period).min()
        highest_high = high.rolling(k_period, min_periods=k_period).max()
        percent_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
        percent_d = percent_k.rolling(d_period, min_periods=d_period).mean()
        return percent_k.fillna(0.0), percent_d.fillna(0.0)
    
    def cci(self, window: int = 20) -> pd.Series:
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]
        tp = (high + low + close) / 3.0
        tp_sma = self.cal_ma(window)
        md = (tp - tp_sma).abs().rolling(window=window, min_periods=window).mean()
        return ((tp - tp_sma) / (0.015 * md)).fillna(0.0)
    
    def roc(self, window: int = 12, col: str = "close") -> pd.Series:
        series = self.df[col]
        return (series / series.shift(window) - 1.0) * 100

    def momentum(self, window: int = 10, col: str = "close") -> pd.Series:
        series = self.df[col]
        return series - series.shift(window)
    
    def obv(self) -> pd.Series:
        close = self.df["close"]
        volume = self.df["quoteAssetVolume"]
        sign = np.sign(close.diff().fillna(0.0))
        return (sign * volume).cumsum()

    def mfi(self, window: int = 14) -> pd.Series:
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]
        volume = self.df["quoteAssetVolume"]

        tp = (high + low + close) / 3.0
        raw_mf = tp * volume
        direction = np.sign(tp.diff())
        pos_mf = raw_mf.where(direction > 0, 0.0)
        neg_mf = raw_mf.where(direction < 0, 0.0).abs()

        pos_sum = pos_mf.rolling(window, min_periods=window).sum()
        neg_sum = neg_mf.rolling(window, min_periods=window).sum().replace(0, np.nan)

        mfr = pos_sum / neg_sum
        mfi_val = 100 - (100 / (1 + mfr))
        return mfi_val.fillna(50.0)

    def vwap(self) -> pd.Series:
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]
        volume = self.df["quoteAssetVolume"]

        tp = (high + low + close) / 3.0
        cum_v = volume.cumsum().replace(0, np.nan)
        cum_pv = (tp * volume).cumsum()
        return (cum_pv / cum_v).ffill().bfill()

    def donchian(self, window: int = 20) -> Tuple[pd.Series, pd.Series]:
        high = self.df["high"]
        low = self.df["low"]
        upper = high.rolling(window, min_periods=window).max()
        lower = low.rolling(window, min_periods=window).min()
        return upper, lower

    def keltner(self, ema_period: int = 20, atr_period: int = 10, mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = self.cal_ema(ema_period)
        atr_val = self.atr(atr_period)
        upper = mid + mult * atr_val
        lower = mid - mult * atr_val
        return mid, upper, lower

    def linear_regression_slope(self, period: int = 20, col: str = 'low') -> Tuple[pd.Series, pd.Series]:
        values = self.df[col].astype(float)

        def _rolling_slope(y: np.ndarray) -> float:
            
            xv = np.arange(y.shape[0])
            A = np.vstack([xv, np.ones_like(xv)]).T
            slope, _ = np.linalg.lstsq(A, y, rcond=None)[0]
            return float(slope)

        slopes = values.rolling(window=period, min_periods=period).apply(_rolling_slope, raw=True)
        direction = np.sign(slopes).fillna(0.0)
        return slopes, direction

    def get_all(self, **kwargs):
        ma_fast_w = kwargs.get("ma_fast_w", 20)
        ma_slow_w = kwargs.get("ma_slow_w", 60)
        ema_fast_w = kwargs.get("ema_fast_w", 20)
        ema_slow_w = kwargs.get("ema_slow_w", 60)
        std_w = kwargs.get("std_w", 20)
        rsi_w = kwargs.get("rsi_w", 14)
        macd_signal = kwargs.get("macd_signal", 9)
        bollinger_k = kwargs.get("bollinger_k", 2.0)
        atr_w = kwargs.get("atr_w", 14)
        kd_k_w = kwargs.get("kd_k_w", 14)
        kd_d_w = kwargs.get("kd_d_w", 14)
        roc_w = kwargs.get("roc_w", 14)
        momentum_w = kwargs.get("momentum_w", 14)
        mfi_w = kwargs.get("mfi_w", 14)
        donchain_w = kwargs.get("donchain_w", 20)
        keltner_m = kwargs.get("keltner_m", 2.0)
        linear_regression_slope_w = kwargs.get("linear_regression_slope_w", 20)


        return {
            "ma_fast": self.cal_ma(window=ma_fast_w).tail,
            "ma_slow": self.cal_ma(window=ma_slow_w),
            "ema_fast": self.cal_ema(window=ema_fast_w),
            "ema_slow": self.cal_ema(window=ema_slow_w),
            "rsi": self.rsi(window=rsi_w),
            "macd": self.macd(fast=ema_fast_w, slow=ema_slow_w, signal=macd_signal),
            "bollinger": self.bollinger(window=ma_fast_w, k=bollinger_k),
            "true_range": self.true_range(),
            "atr": self.atr(atr=atr_w),
            "dmi_adx": self.dmi_adx(window=atr_w),
            "stochastic_kd": self.stochastic_kd(k_period=kd_k_w, d_period=kd_d_w),
            "cci": self.cci(window=ma_fast_w),
            "roc": self.roc(window=roc_w),
            "momentum": self.momentum(window=momentum_w),
            "obv": self.obv()
        }
    
