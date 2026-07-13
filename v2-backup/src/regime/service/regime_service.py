from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.common.constants.regime_constants import (
    ADX_RANGE_THRESHOLD,
    ADX_TREND_THRESHOLD,
    ALLOWED_REGIMES,
    ATR_RISK_DENOM,
    BASELINE_WINDOW,
    BB_RISK_DENOM,
    DEFAULT_EMA_NEAR_PCT,
    DEFAULT_RANGE_ENTRY_ENABLED,
    DOWNTREND,
    EMA_NEAR_CONTEXT_LOOKBACK,
    EMA_NEAR_LOOKBACK,
    EPSILON,
    HYSTERESIS_CONFIRM_COUNT,
    INDICATOR_PARAMS_NAME,
    MIN_15M_CANDLES,
    MIN_1H_CANDLES,
    RANGE,
    REGIME_EMA_NEAR_PCT_ENV,
    REGIME_INTERVAL_15M,
    REGIME_INTERVAL_1H,
    REGIME_RANGE_ENTRY_ENV,
    TRANSITION,
    TRANSITION_ATR_MULT,
    TRANSITION_BB_MULT,
    TREND_ADX_BASE,
    TREND_ADX_SCALE,
    TREND_GAP_DENOM,
    UNKNOWN,
    UPTREND,
)
from src.common.model.params import IndParams
from src.indicators.engine.indicator import Indicator
from src.indicators.service.indicator_parameter.indParam_service import IndicatorParamService
from src.regime.repository.regime_state_repo import RegimeStateRepository
from src.regime.vo.default import (
    DefaultRegimeStateVo,
    RegimeFeatures,
    RegimeResult,
    RegimeScores,
)


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
        self.indParamService = IndicatorParamService()
        self._regime_params_cache = None
        self.range_entry_enabled = (
            os.getenv(REGIME_RANGE_ENTRY_ENV, str(DEFAULT_RANGE_ENTRY_ENABLED)).lower() == "true"
        )
        self.ema_near_pct = float(os.getenv(REGIME_EMA_NEAR_PCT_ENV, str(DEFAULT_EMA_NEAR_PCT)))

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
        ind_params = await self._get_regime_params()
        klines_1h = self.api.get_ohlcv_klines(
            symbol=symbol,
            interval=REGIME_INTERVAL_1H,
            limit=MIN_1H_CANDLES,
        )
        klines_15m = self.api.get_ohlcv_klines(
            symbol=symbol,
            interval=REGIME_INTERVAL_15M,
            limit=MIN_15M_CANDLES,
        )
        raw = await self.classify_regime(
            symbol,
            klines_1h,
            klines_15m,
            ind_params=ind_params,
            computed_at=now,
        )

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
            timeframe=REGIME_INTERVAL_1H,
            regime=regime,
            scores=raw.scores,
            features=raw.features,
            computed_at=now,
        )

    async def classify_regime(
        self,
        symbol: str,
        klines_1h: List[Dict[str, Any]],
        klines_15m: List[Dict[str, Any]],
        ind_params: IndParams,
        computed_at: Optional[datetime] = None,
    ) -> RegimeResult:
        computed_at = computed_at or datetime.now(timezone.utc)
        if len(klines_1h) < MIN_1H_CANDLES or len(klines_15m) < MIN_15M_CANDLES:
            return RegimeResult(
                symbol=symbol,
                timeframe=REGIME_INTERVAL_1H,
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

        indicator_1h = self._build_indicator(klines_1h, ind_params)
        indicator_15m = self._build_indicator(klines_15m, ind_params)
        if indicator_1h is None or indicator_15m is None:
            return RegimeResult(
                symbol=symbol,
                timeframe=REGIME_INTERVAL_1H,
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

        try:
            result = self._classify_from_indicators(
                symbol=symbol,
                indicator_1h=indicator_1h,
                indicator_15m=indicator_15m,
                computed_at=computed_at,
            )
            if result.regime not in ALLOWED_REGIMES:
                raise ValueError(f"invalid regime: {result.regime}")
            return result
        except Exception:
            return RegimeResult(
                symbol=symbol,
                timeframe=REGIME_INTERVAL_1H,
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(),
                computed_at=computed_at,
            )

    def _classify_from_indicators(
        self,
        symbol: str,
        indicator_1h: Indicator,
        indicator_15m: Indicator,
        computed_at: datetime,
    ) -> RegimeResult:
        ema_fast = indicator_1h.ema_fast_series()
        ema_slow = indicator_1h.ema_slow_series()
        bb_mid, bb_upper, bb_lower, bb_bw = indicator_1h.bollinger_series()
        atr_1h = indicator_1h.atr_series()
        atr_15m = indicator_15m.atr_series()
        adx = indicator_1h.adx_series()
        ema_gap = indicator_1h.ema_gap_series()
        ema_gap_ratio = indicator_1h.ema_gap_ratio_series()
        close_series = indicator_1h.close_series()

        adx_last = self._last(adx)
        atr_1h_last = self._last(atr_1h)
        atr_15m_last = self._last(atr_15m)
        bb_last = self._last(bb_bw)
        ema_fast_last = self._last(ema_fast)
        ema_slow_last = self._last(ema_slow)
        ema_gap_last = self._last(ema_gap)
        ema_gap_ratio_last = self._last(ema_gap_ratio)

        atr15_base = self._prev_mean(atr_15m, BASELINE_WINDOW)
        bb_base = self._prev_mean(bb_bw, BASELINE_WINDOW)
        bb_q30 = float(bb_bw.dropna().quantile(0.3))
        atr1h_q30 = float(atr_1h.dropna().quantile(0.3))

        required = [
            adx_last,
            atr_1h_last,
            atr_15m_last,
            bb_last,
            ema_fast_last,
            ema_slow_last,
            atr15_base,
            bb_base,
        ]
        if self._is_invalid(required):
            return RegimeResult(
                symbol=symbol,
                timeframe=REGIME_INTERVAL_1H,
                regime=UNKNOWN,
                scores=RegimeScores(),
                features=RegimeFeatures(
                    adx=adx_last,
                    atr=atr_1h_last,
                    bb_bandwidth=bb_last,
                    ema_gap=ema_gap_last,
                ),
                computed_at=computed_at,
            )

        atr_spike = atr_15m_last > atr15_base * TRANSITION_ATR_MULT
        bb_expand = bb_last > bb_base * TRANSITION_BB_MULT
        ema_cross_or_near = self._ema_cross_or_near(ema_fast, ema_slow, close_series)
        transition = atr_spike or bb_expand or ema_cross_or_near

        if transition:
            regime = TRANSITION
        elif adx_last >= ADX_TREND_THRESHOLD:
            regime = UPTREND if ema_fast_last > ema_slow_last else DOWNTREND
        elif adx_last < ADX_RANGE_THRESHOLD and bb_last <= bb_q30 and atr_1h_last <= atr1h_q30:
            regime = RANGE
        else:
            regime = UNKNOWN

        trend_base = float(np.clip((adx_last - TREND_ADX_BASE) / TREND_ADX_SCALE, 0.0, 1.0))
        trend_gap = float(np.clip(abs(ema_gap_ratio_last) / TREND_GAP_DENOM, 0.0, 1.0))
        trend_strength = float(np.clip(trend_base * (0.5 + 0.5 * trend_gap), 0.0, 1.0))

        range_adx = float(np.clip((ADX_RANGE_THRESHOLD - adx_last) / ADX_RANGE_THRESHOLD, 0.0, 1.0))
        range_bb = float(np.clip((bb_q30 - bb_last) / max(bb_q30, EPSILON), 0.0, 1.0))
        range_atr = float(np.clip((atr1h_q30 - atr_1h_last) / max(atr1h_q30, EPSILON), 0.0, 1.0))
        range_strength = float(np.clip((range_adx + range_bb + range_atr) / 3.0, 0.0, 1.0))

        atr_risk = float(
            np.clip(((atr_15m_last / max(atr15_base, EPSILON)) - 1.0) / ATR_RISK_DENOM, 0.0, 1.0)
        )
        bb_risk = float(
            np.clip(((bb_last / max(bb_base, EPSILON)) - 1.0) / BB_RISK_DENOM, 0.0, 1.0)
        )
        cross_risk = 1.0 if ema_cross_or_near else 0.0
        transition_risk = float(np.clip(max(atr_risk, bb_risk, cross_risk), 0.0, 1.0))

        return RegimeResult(
            symbol=symbol,
            timeframe=REGIME_INTERVAL_1H,
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
                ema_gap=float(ema_gap_last),
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

        if pending_count >= HYSTERESIS_CONFIRM_COUNT:
            return raw_regime, None, 0, now

        return prev_confirmed, pending_regime, pending_count, confirmed_at

    def _build_indicator(self, klines: List[Dict[str, Any]], ind_params: IndParams) -> Optional[Indicator]:
        try:
            return Indicator(ohlcv=klines, indParams=ind_params)
        except Exception:
            return None

    async def _get_regime_params(self) -> IndParams:
        if self._regime_params_cache is None:
            self._regime_params_cache = await self.indParamService.findby_name(INDICATOR_PARAMS_NAME)
        return self._regime_params_cache

    def _ema_cross_or_near(self, ema20: pd.Series, ema60: pd.Series, close: pd.Series) -> bool:
        gap = ema20 - ema60
        sign = np.sign(gap)
        sign_change = sign.diff().fillna(0).abs() > 0
        recent_cross = bool(sign_change.tail(EMA_NEAR_LOOKBACK).any())
        ratio = (gap / close).abs()
        recent_near = bool((ratio.tail(EMA_NEAR_LOOKBACK) <= self.ema_near_pct).any())
        # "near" is only meaningful around an actual recent cross context.
        near_with_cross_context = recent_near and bool(sign_change.tail(EMA_NEAR_CONTEXT_LOOKBACK).any())
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
