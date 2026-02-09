from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.regime.repository.regime_state_repo import RegimeStateRepository
from src.regime.vo.default import (
    DefaultRegimeStateVo,
    RegimeFeatures,
    RegimeResult,
    RegimeScores,
)


UPTREND = "UPTREND"
DOWNTREND = "DOWNTREND"
RANGE = "RANGE"
TRANSITION = "TRANSITION"
UNKNOWN = "UNKNOWN"

ALLOWED_REGIMES = {UPTREND, DOWNTREND, RANGE, TRANSITION, UNKNOWN}

MIN_1H_CANDLES = 200
MIN_15M_CANDLES = 400


@dataclass
class RegimePolicy:
    allow_analyze: bool
    allow_entry: bool
    allowed_sides: Set[str]
    position_size_mult: float
    leverage_mult: float


class RegimeService:
    def __init__(self):
        self.api = OHLCVApi()
        self.repository = RegimeStateRepository()
        self.range_entry_enabled = os.getenv("REGIME_RANGE_ENTRY_ENABLED", "false").lower() == "true"
        self.ema_near_pct = float(os.getenv("REGIME_EMA_NEAR_PCT", "0.0015"))

    def get_policy(self, regime: str) -> RegimePolicy:
        regime_upper = (regime or UNKNOWN).upper()
        if regime_upper == UPTREND:
            return RegimePolicy(True, True, {"BUY"}, 1.0, 1.0)
        if regime_upper == DOWNTREND:
            return RegimePolicy(True, True, {"SELL"}, 1.0, 1.0)
        if regime_upper == RANGE:
            if not self.range_entry_enabled:
                return RegimePolicy(False, False, set(), 0.0, 0.0)
            return RegimePolicy(True, True, {"BUY", "SELL"}, 0.25, 0.6)
        if regime_upper in {TRANSITION, UNKNOWN}:
            return RegimePolicy(False, False, set(), 0.0, 0.0)
        return RegimePolicy(False, False, set(), 0.0, 0.0)

    async def get_current_regime(self, symbol: str) -> DefaultRegimeStateVo:
        current = await self.repository.select_by_symbol(symbol)
        if current:
            return current
        return DefaultRegimeStateVo(symbol_id=symbol, regime=UNKNOWN)

    async def compute_regime(self, symbol: str) -> RegimeResult:
        now = datetime.now(timezone.utc)
        klines_1h = self.api.get_ohlcv_klines(symbol=symbol, interval="1h", limit=MIN_1H_CANDLES)
        klines_15m = self.api.get_ohlcv_klines(symbol=symbol, interval="15m", limit=MIN_15M_CANDLES)
        raw = self.classify_regime(symbol, klines_1h, klines_15m, computed_at=now)

        prev_state = await self.repository.select_by_symbol(symbol)
        regime, pending_regime, pending_count, confirmed_at = self._apply_hysteresis(
            previous=prev_state,
            raw_regime=raw.regime,
            now=now,
        )

        next_state = DefaultRegimeStateVo(
            symbol_id=symbol,
            timeframe=raw.timeframe,
            regime=regime,
            pending_regime=pending_regime,
            pending_count=pending_count,
            trend_strength=raw.scores.trend_strength,
            range_strength=raw.scores.range_strength,
            transition_risk=raw.scores.transition_risk,
            adx=raw.features.adx,
            atr=raw.features.atr,
            bb_bandwidth=raw.features.bb_bandwidth,
            ema_gap=raw.features.ema_gap,
            computed_at=now,
            confirmed_at=confirmed_at,
        )
        await self.repository.upsert(next_state)

        logger.info(
            f"[{symbol}][{regime}]"
            f"[adx={next_state.adx}]"
            f"[atr={next_state.atr}]"
            f"[bb_bw={next_state.bb_bandwidth}]"
            f"[ema_gap={next_state.ema_gap}]"
        )

        return RegimeResult(
            symbol=symbol,
            timeframe="1h",
            regime=regime,
            scores=raw.scores,
            features=raw.features,
            computed_at=now,
        )

    def classify_regime(
        self,
        symbol: str,
        klines_1h: List[Dict[str, Any]],
        klines_15m: List[Dict[str, Any]],
        computed_at: Optional[datetime] = None,
    ) -> RegimeResult:
        computed_at = computed_at or datetime.now(timezone.utc)
        if len(klines_1h) < MIN_1H_CANDLES or len(klines_15m) < MIN_15M_CANDLES:
            return RegimeResult(
                symbol=symbol,
                timeframe="1h",
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

        df_1h = self._to_price_frame(klines_1h)
        df_15m = self._to_price_frame(klines_15m)
        if df_1h is None or df_15m is None:
            return RegimeResult(
                symbol=symbol,
                timeframe="1h",
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

        try:
            result = self._classify_from_frames(symbol=symbol, df_1h=df_1h, df_15m=df_15m, computed_at=computed_at)
            if result.regime not in ALLOWED_REGIMES:
                raise ValueError(f"invalid regime: {result.regime}")
            return result
        except Exception:
            return RegimeResult(
                symbol=symbol,
                timeframe="1h",
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

    def _classify_from_frames(
        self,
        symbol: str,
        df_1h: pd.DataFrame,
        df_15m: pd.DataFrame,
        computed_at: datetime,
    ) -> RegimeResult:
        ema20 = self._ema(df_1h["close"], 20)
        ema60 = self._ema(df_1h["close"], 60)
        bb_mid, bb_upper, bb_lower = self._bollinger(df_1h["close"], 20, 2.0)
        bb_bw = (bb_upper - bb_lower) / bb_mid
        atr_1h = self._atr(df_1h, 14)
        atr_15m = self._atr(df_15m, 14)
        adx = self._adx(df_1h, 14)

        adx_last = self._last(adx)
        atr_1h_last = self._last(atr_1h)
        atr_15m_last = self._last(atr_15m)
        bb_last = self._last(bb_bw)
        ema20_last = self._last(ema20)
        ema60_last = self._last(ema60)
        close_last = self._last(df_1h["close"])
        ema_gap = ema20_last - ema60_last
        ema_gap_ratio = ema_gap / close_last if close_last else np.nan

        atr15_base = self._prev_mean(atr_15m, 20)
        bb_base = self._prev_mean(bb_bw, 20)
        bb_q30 = float(bb_bw.dropna().quantile(0.3))
        atr1h_q30 = float(atr_1h.dropna().quantile(0.3))

        required = [adx_last, atr_1h_last, atr_15m_last, bb_last, ema20_last, ema60_last, atr15_base, bb_base]
        if self._is_invalid(required):
            return RegimeResult(
                symbol=symbol,
                timeframe="1h",
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(adx=adx_last, atr=atr_1h_last, bb_bandwidth=bb_last, ema_gap=ema_gap),
                computed_at=computed_at,
            )

        atr_spike = atr_15m_last > atr15_base * 1.8
        bb_expand = bb_last > bb_base * 1.7
        ema_cross_or_near = self._ema_cross_or_near(ema20, ema60, df_1h["close"])
        transition = atr_spike or bb_expand or ema_cross_or_near

        if transition:
            regime = TRANSITION
        elif adx_last >= 25:
            regime = UPTREND if ema20_last > ema60_last else DOWNTREND
        elif adx_last < 20 and bb_last <= bb_q30 and atr_1h_last <= atr1h_q30:
            regime = RANGE
        else:
            regime = UNKNOWN

        trend_base = float(np.clip((adx_last - 20.0) / 20.0, 0.0, 1.0))
        trend_gap = float(np.clip(abs(ema_gap_ratio) / 0.01, 0.0, 1.0))
        trend_strength = float(np.clip(trend_base * (0.5 + 0.5 * trend_gap), 0.0, 1.0))

        range_adx = float(np.clip((20.0 - adx_last) / 20.0, 0.0, 1.0))
        range_bb = float(np.clip((bb_q30 - bb_last) / max(bb_q30, 1e-8), 0.0, 1.0))
        range_atr = float(np.clip((atr1h_q30 - atr_1h_last) / max(atr1h_q30, 1e-8), 0.0, 1.0))
        range_strength = float(np.clip((range_adx + range_bb + range_atr) / 3.0, 0.0, 1.0))

        atr_risk = float(np.clip(((atr_15m_last / max(atr15_base, 1e-8)) - 1.0) / 0.8, 0.0, 1.0))
        bb_risk = float(np.clip(((bb_last / max(bb_base, 1e-8)) - 1.0) / 0.7, 0.0, 1.0))
        cross_risk = 1.0 if ema_cross_or_near else 0.0
        transition_risk = float(np.clip(max(atr_risk, bb_risk, cross_risk), 0.0, 1.0))

        return RegimeResult(
            symbol=symbol,
            timeframe="1h",
            regime=regime,
            scores=RegimeScores(
                trend_strength=trend_strength,
                range_strength=range_strength,
                transition_risk=transition_risk,
            ),
            features=RegimeFeatures(
                adx=float(adx_last),
                atr=float(atr_1h_last),
                bb_bandwidth=float(bb_last),
                ema_gap=float(ema_gap),
            ),
            computed_at=computed_at,
        )

    def _apply_hysteresis(
        self,
        previous: Optional[DefaultRegimeStateVo],
        raw_regime: str,
        now: datetime,
    ) -> Tuple[str, Optional[str], int, Optional[datetime]]:
        prev_confirmed = (previous.regime if previous else UNKNOWN) or UNKNOWN
        pending_regime = previous.pending_regime if previous else None
        pending_count = int(previous.pending_count or 0) if previous else 0
        confirmed_at = previous.confirmed_at if previous else None

        if raw_regime == prev_confirmed:
            return prev_confirmed, None, 0, confirmed_at

        if pending_regime == raw_regime:
            pending_count += 1
        else:
            pending_regime = raw_regime
            pending_count = 1

        if pending_count >= 2:
            return raw_regime, None, 0, now

        return prev_confirmed, pending_regime, pending_count, confirmed_at

    def _to_price_frame(self, klines: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
        try:
            frame = pd.DataFrame(klines)
            frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
            frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
            frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
            frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
            frame = frame[["open", "high", "low", "close"]]
            return frame
        except Exception:
            return None

    @staticmethod
    def _ema(series: pd.Series, window: int) -> pd.Series:
        return series.ewm(span=window, adjust=False, min_periods=window).mean()

    @staticmethod
    def _bollinger(series: pd.Series, window: int, k: float) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = series.rolling(window=window, min_periods=window).mean()
        std = series.rolling(window=window, min_periods=window).std(ddof=0)
        upper = mid + k * std
        lower = mid - k * std
        return mid, upper, lower

    @staticmethod
    def _atr(df: pd.DataFrame, window: int) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    def _adx(self, df: pd.DataFrame, window: int) -> pd.Series:
        high = df["high"]
        low = df["low"]
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr = self._atr(df, window)

        plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
            alpha=1 / window,
            adjust=False,
            min_periods=window,
        ).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
            alpha=1 / window,
            adjust=False,
            min_periods=window,
        ).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    def _ema_cross_or_near(self, ema20: pd.Series, ema60: pd.Series, close: pd.Series) -> bool:
        gap = ema20 - ema60
        sign = np.sign(gap)
        sign_change = sign.diff().fillna(0).abs() > 0
        recent_cross = bool(sign_change.tail(3).any())
        ratio = (gap / close).abs()
        recent_near = bool((ratio.tail(3) <= self.ema_near_pct).any())
        # "near" is only meaningful around an actual recent cross context.
        near_with_cross_context = recent_near and bool(sign_change.tail(6).any())
        return recent_cross or near_with_cross_context

    @staticmethod
    def _last(series: pd.Series) -> float:
        return float(series.iloc[-1])

    @staticmethod
    def _prev_mean(series: pd.Series, n: int) -> float:
        clean = series.dropna()
        if len(clean) <= n:
            return float(clean.tail(n).mean()) if len(clean) > 0 else np.nan
        return float(clean.iloc[-(n + 1):-1].mean())

    @staticmethod
    def _is_invalid(values: List[Any]) -> bool:
        for value in values:
            if value is None:
                return True
            try:
                if not np.isfinite(float(value)):
                    return True
            except Exception:
                return True
        return False
