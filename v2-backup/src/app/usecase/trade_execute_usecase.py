from loguru import logger
from pydantic import BaseModel

from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto
from src.binance.service.trader.trade_service import TradeService
from src.common.constants.job_constants import JOB_TYPE_POSITION_OPEN, JOB_STATUS_DONE, JOB_TYPE_POSITION_OPEN_FAIL
from src.common.exception import InvalidRequestException, DataNotFoundException, RepositoryError, ExternalApiError
from src.job.service.job.job_run_service import JobRunService
from src.job.vo.job.default import DefaultJobRunVo


class OpenPositionDto(BaseModel):
    symbol_id: str
    batch_id: str
    side: str
    confidence: float
    entry_price: float
    tp: float
    sl: float

class ClosePositionDto(BaseModel):
    symbol_id: str

class TradeExecuteUseCase:
    def __init__(self):
        self.trade_service = TradeService()
        self.job_service = JobRunService()

    async def open_execute(self, dto: OpenPositionDto):
        try:
            await self.job_service.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN, status=JOB_STATUS_DONE
                ))
            response = await self.trade_service.open_from_analyze(TradeExecuteDto(**dto.model_dump()))
            m_response = response.get('main_response')
            tp_response = response.get('tp_response')
            sl_response = response.get('sl_response')
            if dto.batch_id:
                await self.job_service.update_job_run(DefaultJobRunVo(
                    batch_id=dto.batch_id,
                    main_order_id=m_response.get('clientOrderId'),
                    tp_order_id=tp_response.get('clientAlgoId'),
                    sl_order_id=sl_response.get('clientAlgoId'),
                ))
                return response
        except (InvalidRequestException, DataNotFoundException) as e:
            logger.warning(f"tradeExecutor.open_from_analyze: {e}")
            await self.job_service.update_job_run(DefaultJobRunVo(
                batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN_FAIL, status=JOB_STATUS_DONE
            ))
            return None
        except (ExternalApiError, RepositoryError) as e:
            logger.error(f"tradeExecutor.open_from_analyze: {e}")
            await self.job_service.update_job_run(DefaultJobRunVo(
                batch_id=dto.batch_id, job_type=JOB_TYPE_POSITION_OPEN_FAIL, status=JOB_STATUS_DONE
            ))
            raise

    async def close_execute(self, dto: ClosePositionDto):
        self.trade_service.close_position(dto.symbol_id)