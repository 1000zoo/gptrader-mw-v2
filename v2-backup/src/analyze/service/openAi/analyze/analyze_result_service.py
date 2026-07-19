from typing import List
from loguru import logger

from src.analyze.repository.openAi.analyze.analyze_result_repo import AnalyzeResultRepository
from src.analyze.vo.openAi.analyze.analyze_result_vo_default import DefaultAnalyzeResultVo
from src.analyze.api.openAi.openAi_api import OpenAiApi
from src.analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.common.model.params import IndParams
from src.common.model.base import OhlcvMeta
from src.common.model.response import GptChatResponse
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

def _to_vo(result: GptChatResponse, **meta) -> DefaultAnalyzeResultVo:
    return DefaultAnalyzeResultVo(
        **result.model_dump(),
        **meta
    )

class AnalyzeResultService:
    def __init__(self):
        self.repository = AnalyzeResultRepository()
        self.aiApi = OpenAiApi()
        self.pm = BasePromptManager()    # :: 기능으로 구현 (vo, repo, service)

    async def analyze(self,
                 ohlcv: List[DefaultOhlcvVo],
                 indicators: List[DefaultIndicatorVo],
                 indParams:  IndParams) -> DefaultAnalyzeResultVo:
        if not (ohlcv and indicators):
            logger.error("ERROR!")
            raise InvalidRequestException("OHLCV and indicator data are required for analysis.")
        sample = ohlcv[0]
        ohlcvMeta = OhlcvMeta(
            symbol=sample.symbol_id,
            interval=sample.c_interval,
            limit=sample.c_limit
        )

        prompts = self.pm.generate_from(
            ohlcv=[o.dump_for_prompt() for o in ohlcv],
            indicators=[i.dump_for_prompt() for i in indicators],
            ohlcvMeta=ohlcvMeta,
            indParams=indParams
        )
        meta = {
            'batch_id': sample.batch_id,
            'prompt_id': prompts.prompt_set_id,
            'symbol_id': sample.symbol_id,
            'reg_ymd': sample.reg_ymd
        }

        try:
            result = self.aiApi.chat(prompts)
        except ExternalApiError as e:
            raise ExternalApiError("OpenAI chat call failed.") from e
        logger.info(f"result: {result}")
        result_vo = _to_vo(result, **meta)
        try:
            await self.repository.insert_result(result_vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert analyze result.") from e

        return result_vo
