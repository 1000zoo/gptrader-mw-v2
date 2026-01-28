import json

from typing import Dict, List, Any
from loguru import logger

from src.analyze.repository.openAi.analyze.analyze_action_repo import AnalyzeActionRepository
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.analyze.vo.openAi.analyze.analyze_result_vo_default import DefaultAnalyzeResultVo
from src.analyze.vo.openAi.analyze.analyze_action_vo_filter import AnalyzeActionFilterVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

def _convert(result: DefaultAnalyzeResultVo) -> DefaultAnalyzeActionVo:
    action_text = result.raw_content
    try:
        action = json.loads(action_text)
    except json.JSONDecodeError as e:
        logger.error(f"invalid format: {action_text}, ==> {e}")
        raise InvalidRequestException("Analyze action response is not valid JSON.") from e

    return DefaultAnalyzeActionVo(**action, **result.model_dump(exclude_defaults=True))


class AnalyzeActionService:
    def __init__(self):
        self.repository = AnalyzeActionRepository()

    async def insert_action(self, vo: DefaultAnalyzeResultVo) -> DefaultAnalyzeActionVo:
        converted_vo = _convert(vo)
        try:
            await self.repository.insert_action(converted_vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert analyze action.") from e
        return converted_vo

    async def select_action(self, vo: AnalyzeActionFilterVo) -> DefaultAnalyzeActionVo:
        try:
            action = await self.repository.select_action(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select analyze action.") from e
        if not action:
            raise DataNotFoundException("Analyze action not found.")
        return action
