from loguru import logger

from src.signal.service.signal_log.signal_log_service import SignalLogService
from src.signal.vo.signal_log.default import DefaultSignalLogVo

from src.analyze.service.openAi.analyze.analyze_action_service import AnalyzeActionService
from src.analyze.service.openAi.analyze.analyze_result_service import AnalyzeResultService
from src.analyze.dto.openAi.analyze.analyze_input_dto import AnalyzeInputDto
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.analyze.vo.openAi.analyze.analyze_action_vo_filter import AnalyzeActionFilterVo

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
        analyze_input: AnalyzeInputDto,
        action: DefaultAnalyzeActionVo,
        result_id: int | None = None,
        action_id: int | None = None,
        prompt_version: str | None = None,
        model_name: str | None = None,
    ) -> None:
        ohlcv = analyze_input.ohlcv
        if not ohlcv:
            return
        ts_list = [o.ts for o in ohlcv if o.ts]
        base_ts = max(ts_list) if ts_list else None
        window_start_ts = min(ts_list) if ts_list else None
        window_end_ts = max(ts_list) if ts_list else None
        sample = ohlcv[0]
        raw_position = "WAIT" if action.side in (None, "NONE") else action.side
        final_action = "WAIT" if raw_position == "WAIT" else "EXECUTED"
        signal_log = DefaultSignalLogVo(
            run_id=sample.batch_id,
            job_run_id=sample.batch_id,
            symbol_id=sample.symbol_id,
            c_interval=sample.c_interval,
            base_ts=base_ts,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            n_candles=len(ohlcv),
            indicator_params_version=analyze_input.indParams.name,
            prompt_version=prompt_version,
            model_name=model_name,
            raw_position=raw_position,
            raw_confidence=self._normalize_confidence(action.confidence),
            tp_price=action.tp,
            sl_price=action.sl,
            rationale=action.reason,
            final_action=final_action,
            analyze_result_id=result_id,
            analyze_action_id=action_id,
        )
        await self.signal_log_service.create_signal_log(signal_log)

    async def analyze(self, analyzeInputDto: AnalyzeInputDto) -> DefaultAnalyzeActionVo:
        result = await self.result_service.analyze(
            ohlcv=analyzeInputDto.ohlcv, indicators=analyzeInputDto.indicators, indParams=analyzeInputDto.indParams
        )
        action = await self.action_service.insert_action(result)

        await self._record_signal_log(
            analyze_input=analyzeInputDto,
            action=action,
            result_id=result.id,
            action_id=action.id,
            prompt_version=result.prompt_id,
            model_name=result.model,
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
