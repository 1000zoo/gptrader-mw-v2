from loguru import logger

from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto
from src.binance.service.trader.trade_service import TradeService
from src.job.service.job.job_run_service import JobRunService
from src.job.vo.job.default import DefaultJobRunVo

from src.common.constants.job_constants import (
    JOB_TYPE_POSITION_OPEN_FAIL,
    JOB_TYPE_POSITION_OPEN,
    JOB_STATUS_DONE
)
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError

class TradeExecutor:
    def __init__(self):
        self.tradeService = TradeService()
        self.jobRunService = JobRunService()

    async def open_from_analyze(self, dto: TradeExecuteDto):
        try:
            await self.jobRunService.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN, status=JOB_STATUS_DONE
                ))
            response = await self.tradeService.open_from_analyze(dto)
            m_response = response.get('main_response')
            tp_response = response.get('tp_response')
            sl_response = response.get('sl_response')
            if dto.batch_id:
                await self.jobRunService.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id,
                    main_order_id=m_response.get('clientOrderId'),
                    tp_order_id=tp_response.get('clientAlgoId'),
                    sl_order_id=sl_response.get('clientAlgoId'),
                ))
            return response
        except (InvalidRequestException, DataNotFoundException) as e:
            logger.warning(f"tradeExecutor.open_from_analyze: {e}")
            await self.jobRunService.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN_FAIL, status=JOB_STATUS_DONE
                ))
            return None
        except (ExternalApiError, RepositoryError) as e:
            logger.error(f"tradeExecutor.open_from_analyze: {e}")
            await self.jobRunService.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN_FAIL, status=JOB_STATUS_DONE
                ))
            raise
