from typing import Optional

from loguru import logger

from src.analyze.dto.openAi.analyze.analyze_input_dto import AnalyzeInputDto
from src.analyze.service.openAi.analyze.analyze_service import AnalyzeService
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError


class AnalyzeExecutor:
    def __init__(self):
        self.analyzeService = AnalyzeService()

    async def analyze(self, dto: AnalyzeInputDto) -> Optional[DefaultAnalyzeActionVo]:
        try:
            return await self.analyzeService.analyze(dto)
        except (DataNotFoundException, InvalidRequestException) as e:
            logger.warning(f"analyzeExecutor.analyze: {e}")
            return None
        except (ExternalApiError, RepositoryError) as e:
            logger.error(f"analyzeExecutor.analyze: {e}")
            raise

    async def select_batch_id(self, batch_id: str) -> Optional[DefaultAnalyzeActionVo]:
        try:
            return await self.analyzeService.select_batch_id(batch_id)
        except DataNotFoundException as e:
            logger.warning(f"analyzeExecutor.select: {e}")
            return None
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"analyzeExecutor.select: {e}")
            raise
