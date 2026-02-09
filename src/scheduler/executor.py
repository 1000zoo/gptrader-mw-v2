from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from loguru import logger

from src.analyze.dto.openAi.analyze.analyze_input_dto import AnalyzeInputDto
from src.analyze.executor.openAi.analyze.analyze_executor import AnalyzeExecutor
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto
from src.binance.executor.ohlcv.ohlcv_executor import OhlcvExecutor
from src.binance.executor.symbol.symbol_executor import SymbolExecutor
from src.binance.executor.trader.account_executor import AccountExecutor
from src.binance.executor.trader.trade_executor import TradeExecutor
from src.binance.vo.symbol.default import DefaultSymbolVo
from src.common.model.params import IndParams
from src.common.util.date import reg_ymd_now
from src.indicators.executor.indicator.indicator_executor import IndicatorExecutor
from src.job.executor.job.job_executor import JobExecutor
from src.job.vo.job.default import DefaultJobRunVo
from src.regime.service.regime_service import RegimePolicy, RegimeService
from src.common.constants.job_constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_ERROR,
    JOB_STATUS_RUNNING,
    JOB_TYPE_ANALYZE_ACTION,
    JOB_TYPE_ANALYZE_RESULT,
    JOB_TYPE_CREATED,
    JOB_TYPE_INDICATOR_DONE,
    JOB_TYPE_OHLCV_LOADED,
    JOB_TYPE_POSITION_OPEN,
)
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError


class SchedulerExecutor:
    def __init__(self, interval: str = "1h", limit: int = 150, indParams: Optional[IndParams] = None):
        self.interval = interval
        self.limit = limit
        self.indParams = indParams or IndParams()
        self.symbolExecutor = SymbolExecutor()
        self.ohlcvExecutor = OhlcvExecutor()
        self.indicatorExecutor = IndicatorExecutor()
        self.analyzeExecutor = AnalyzeExecutor()
        self.tradeExecutor = TradeExecutor()
        self.jobExecutor = JobExecutor()
        self.accountExecutor = AccountExecutor()
        self.regimeService = RegimeService()

    async def execute(self):
        try:
            if await self._has_open_position():
                # logger.info("skip scheduler: open position already exists.")
                return None

            await self.jobExecutor.delete_all_old_job()

            symbols = await self.symbolExecutor.get_symbol_list()
            if not symbols:
                logger.info("no symbols to process.")
                return None
            logger.info(f"symbols loaded: {[symbol.symbol_id for symbol in symbols]}")

            actions: List[DefaultAnalyzeActionVo] = []
            action_policy: dict[str, RegimePolicy] = {}

            failed_action = await self.jobExecutor.get_failed_job()
            if failed_action:
                action = await self.analyzeExecutor.select_batch_id(batch_id=failed_action.batch_id)
                if not action:
                    logger.error(
                        f"skip scheduler: failed position detected, but has no analyze action: {failed_action.batch_id}"
                    )
                    await self.jobExecutor.delete_job_run(failed_action.batch_id)
                    return None
                if action:
                    if not action.symbol_id:
                        logger.warning("failed action has no symbol_id, skip")
                        return None
                    regime_result = await self.regimeService.compute_regime(action.symbol_id)
                    filtered = self._apply_regime_policy(action, regime_result.regime)
                    if filtered:
                        actions.append(filtered)
                        action_policy[self._action_key(filtered)] = self.regimeService.get_policy(regime_result.regime)
            else:
                for symbol in symbols:
                    regime_result = await self.regimeService.compute_regime(symbol.symbol_id)
                    policy = self.regimeService.get_policy(regime_result.regime)
                    if not policy.allow_analyze:
                        logger.info(f"skip analyze by regime policy: {symbol.symbol_id} [{regime_result.regime}]")
                        continue
                    action = await self._run_symbol(symbol)
                    if not action:
                        continue
                    filtered = self._apply_regime_policy(action, regime_result.regime)
                    if filtered:
                        actions.append(filtered)
                        action_policy[self._action_key(filtered)] = policy

            if not actions:
                logger.info("no analyze action generated.")
                return None

            filtered_actions = [action for action in actions if (action.side or "").lower() not in {"wait", "none"}]
            if not filtered_actions:
                logger.info("no actionable analyze results generated.")
                return None
            best_action = max(filtered_actions, key=lambda item: item.confidence or 0)
            await self._cleanup_unselected(actions, best_action.batch_id)
            logger.info(f"best action => {best_action.symbol_id} {best_action.side}, reason: {best_action.reason}")

            selected_policy = action_policy.get(self._action_key(best_action), RegimePolicy(True, True, {"BUY", "SELL"}, 1.0, 1.0))

            trade_result = await self.tradeExecutor.open_from_analyze(
                TradeExecuteDto(
                    symbol_id=best_action.symbol_id or "",
                    side=best_action.side or "",
                    entry_price=best_action.entry_price,
                    tp=best_action.tp,
                    sl=best_action.sl,
                    confidence=best_action.confidence,
                    reason=best_action.reason,
                    batch_id=best_action.batch_id,
                    c_interval=self.interval,
                    regime=self._extract_regime_tag(best_action.reason),
                    position_size_mult=selected_policy.position_size_mult,
                    leverage_mult=selected_policy.leverage_mult,
                )
            )
            if trade_result:
                await self._update_job(
                    best_action.batch_id,
                    JOB_TYPE_POSITION_OPEN,
                    JOB_STATUS_DONE,
                    best_action.symbol_id,
                )
            else:
                pass
                # await self.jobExecutor.delete_job_run(best_action.batch_id)
                # await self._update_job(best_action.batch_id, JOB_TYPE_ANALYZE_ACTION, JOB_STATUS_DONE)

            return trade_result
        except (DataNotFoundException, InvalidRequestException) as e:
            logger.warning(f"schedulerExecutor.execute: {e}")
            return None
        except (ExternalApiError, RepositoryError) as e:
            logger.error(f"schedulerExecutor.execute: {e}")
            raise

    async def _has_open_position(self) -> bool:
        # batch_ids = await self.jobExecutor.get_running_batch_ids(job_type=JOB_TYPE_POSITION_OPEN)
        # return bool(batch_ids)
        return self.accountExecutor.has_position()

    async def _run_symbol(self, symbol: DefaultSymbolVo) -> Optional[DefaultAnalyzeActionVo]:
        if not symbol or not symbol.symbol_id:
            raise InvalidRequestException("Symbol is required to run analysis.")

        batch_id = await self._generate_batch_id(symbol.symbol_id)
        await self.jobExecutor.create_job_run(
            DefaultJobRunVo(
                batch_id=batch_id,
                job_type=JOB_TYPE_CREATED,
                reg_ymd=reg_ymd_now(),
                target_interval=self.interval,
                symbol_id=symbol.symbol_id,
                status=JOB_STATUS_RUNNING,
            )
        )
        logger.info(f"job progress [{symbol.symbol_id}] {batch_id} {JOB_TYPE_CREATED} {JOB_STATUS_RUNNING}")

        ohlcv = await self.ohlcvExecutor.load_ohlcv(
            symbol_name=symbol.symbol_id,
            interval=self.interval,
            limit=self.limit,
            batch_id=batch_id,
        )
        if not ohlcv:
            await self._update_job(batch_id, JOB_TYPE_OHLCV_LOADED, JOB_STATUS_ERROR, symbol.symbol_id)
            return None

        await self._update_job(batch_id, JOB_TYPE_OHLCV_LOADED, JOB_STATUS_RUNNING, symbol.symbol_id)

        indicators = await self.indicatorExecutor.cal_insert_indicators(ohlcv, self.indParams)
        if not indicators:
            await self._update_job(batch_id, JOB_TYPE_INDICATOR_DONE, JOB_STATUS_ERROR, symbol.symbol_id)
            return None

        await self._update_job(batch_id, JOB_TYPE_INDICATOR_DONE, JOB_STATUS_RUNNING, symbol.symbol_id)
        await self._update_job(batch_id, JOB_TYPE_ANALYZE_RESULT, JOB_STATUS_RUNNING, symbol.symbol_id)

        analyze_input = AnalyzeInputDto(ohlcv=ohlcv, indicators=indicators, indParams=self.indParams)
        action = await self.analyzeExecutor.analyze(analyze_input)
        if not action:
            await self._update_job(batch_id, JOB_TYPE_ANALYZE_RESULT, JOB_STATUS_ERROR, symbol.symbol_id)
            return None

        await self._update_job(batch_id, JOB_TYPE_ANALYZE_ACTION, JOB_STATUS_RUNNING, symbol.symbol_id)
        return action

    async def _cleanup_unselected(self, actions: List[DefaultAnalyzeActionVo], selected_batch_id: Optional[str]):
        for action in actions:
            if action.batch_id and action.batch_id != selected_batch_id:
                await self.jobExecutor.delete_job_run(action.batch_id)

    async def _update_job(
        self,
        batch_id: Optional[str],
        job_type: str,
        status: str,
        symbol_id: Optional[str] = None,
    ):
        if not batch_id:
            return
        if symbol_id:
            logger.info(f"job progress [{symbol_id}] {batch_id} {job_type} {status}")
        await self.jobExecutor.update_job_run(
            DefaultJobRunVo(
                batch_id=batch_id,
                job_type=job_type,
                status=status,
            )
        )

    async def _generate_batch_id(self, symbol_id: str) -> str:
        n = await self.symbolExecutor.get_today_n(DefaultSymbolVo(symbol_id=symbol_id))
        return f"{symbol_id}{reg_ymd_now()}{n}"

    @staticmethod
    def _normalize_action_side(side: Optional[str]) -> Optional[str]:
        if not side:
            return None
        side_upper = side.upper()
        if side_upper in {"LONG", "BUY"}:
            return "BUY"
        if side_upper in {"SHORT", "SELL"}:
            return "SELL"
        return None

    def _apply_regime_policy(self, action: DefaultAnalyzeActionVo, regime: str) -> Optional[DefaultAnalyzeActionVo]:
        policy = self.regimeService.get_policy(regime)
        normalized_side = self._normalize_action_side(action.side)

        if not policy.allow_entry:
            logger.info(f"skip entry by regime policy: {action.symbol_id} [{regime}]")
            return None

        if normalized_side and policy.allowed_sides and normalized_side not in policy.allowed_sides:
            logger.info(f"skip side by regime policy: {action.symbol_id} {action.side} [{regime}]")
            return None

        reason = action.reason or ""
        action.reason = f"{reason} [regime={regime}]".strip()
        return action

    @staticmethod
    def _extract_regime_tag(reason: Optional[str]) -> Optional[str]:
        if not reason:
            return None
        start = reason.rfind("[regime=")
        if start < 0:
            return None
        end = reason.find("]", start)
        if end < 0:
            return None
        return reason[start + 8:end]

    @staticmethod
    def _action_key(action: DefaultAnalyzeActionVo) -> str:
        return action.batch_id or action.symbol_id or "unknown"


async def execute():
    executor = SchedulerExecutor()
    # logger.info("scheduler START!")
    return await executor.execute()
