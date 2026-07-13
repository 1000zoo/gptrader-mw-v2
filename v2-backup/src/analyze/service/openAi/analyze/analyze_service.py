from typing import List

from loguru import logger

from src.analyze.dto.openAi.analyze.analyze_input_dto import AnalyzeInputDto
from src.analyze.service.openAi.analyze.analyze_action_service import AnalyzeActionService
from src.analyze.service.openAi.analyze.analyze_result_service import AnalyzeResultService
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.analyze.vo.openAi.analyze.analyze_action_vo_filter import AnalyzeActionFilterVo
from src.analyze.vo.openAi.analyze.analyze_result_vo_default import DefaultAnalyzeResultVo
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.signal.service.signal_log.signal_log_service import SignalLogService
from src.signal.vo.signal_log.default import DefaultSignalLogVo


class AnalyzeService:
    def __init__(self):
        self.action_service = AnalyzeActionService()
        self.result_service = AnalyzeResultService()
        self.signal_log_service = SignalLogService()

    @staticmethod
    def _normalize_confidence(confidence: float | None) -> float | None:
        if confidence is None:
            return None
        return confidence / 100.0 if confidence > 1 else confidence

    async def _record_signal_log(
        self,
        result: DefaultAnalyzeResultVo,
        action: DefaultAnalyzeActionVo,
        ohlcvs: List[DefaultOhlcvVo],
        indicator_params_version: str,
    ) -> None:
        sample = ohlcvs[0]
        window_start_ts = min([ohlcv.ts for ohlcv in ohlcvs])
        window_end_ts = max([ohlcv.ts for ohlcv in ohlcvs])
        raw_position = action.side
        final_action = action.side
        signal_log = DefaultSignalLogVo(
            run_id=sample.batch_id,
            job_run_id=sample.batch_id,
            symbol_id=sample.symbol_id,
            c_interval=sample.c_interval,
            base_ts=window_end_ts,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            n_candles=sample.c_limit,
            indicator_params_version=indicator_params_version,
            prompt_version=result.prompt_id,
            model_name=result.model,
            raw_position=raw_position,
            raw_confidence=self._normalize_confidence(action.confidence),
            tp_price=action.tp,
            sl_price=action.sl,
            rationale=action.reason,
            final_action=final_action,
            analyze_result_id=result.id,
            analyze_action_id=action.id,
        )
        await self.signal_log_service.create_signal_log(signal_log)

    async def analyze(self, analyzeInputDto: AnalyzeInputDto) -> DefaultAnalyzeActionVo:
        result = await self.result_service.analyze(
            ohlcv=analyzeInputDto.ohlcv, indicators=analyzeInputDto.indicators, indParams=analyzeInputDto.indParams
        )
        action = await self.action_service.insert_action(result)

        await self._record_signal_log(
            result=result,
            action=action,
            ohlcvs=analyzeInputDto.ohlcv,
            indicator_params_version=analyzeInputDto.indParams.name
        )

        sample = analyzeInputDto.ohlcv[0] if analyzeInputDto.ohlcv else None
        logger.bind(
            run_id=result.batch_id,
            symbol=action.symbol_id,
            timeframe=sample.c_interval if sample else None,
            action_id=action.id,
            job_id=action.batch_id,
            order_id=None,
            signal_log_id=None,
        ).info(f"analyze result about {action.symbol_id} => {action.side}")
        return action

    async def select_batch_id(self, batch_id: str) -> DefaultAnalyzeActionVo:
        return await self.action_service.select_action(AnalyzeActionFilterVo(
            batch_id=batch_id
        ))
