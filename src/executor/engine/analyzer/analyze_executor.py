from typing import Dict, List
from loguru import logger

from src.common.config import THRESHOLD

from src.analyze.api.openAi.openAi_api import OpenAiApi
from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.common.model.base import OhlcvMeta
from src.common.model.params import IndParams
from src.common.class_config.prompt_manager_config import get_prompt_manager
from src.indicators.engine.indicator import Indicator
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.invalid_response_exception import InvalidResponseException

class AnalyzeExecutor:
    def __init__(self,
                 indParams: IndParams = IndParams(),
                 ):
        self.openAiApi = OpenAiApi()
        self.ohlcvApi = OHLCVApi()
        self.indParams = indParams
        self.pm = get_prompt_manager()
    
    def analyze_execute(self, symbols: List, interval: str, limit: int):
        recommends = []
        for i, prompt in enumerate(self.generate_prompt(symbols, interval, limit)):
            try:
                resp = self.openAiApi.chat(prompts=prompt)
                ## 결과 DB insert 작업 추가
                recommend = resp.recommend
                side = recommend.get("side", "wait")
                confidence = float(recommend.get("confidence", 0.0))
                logger.info(f"rrrr:: {recommend}")
                if side != "wait" and confidence >= THRESHOLD:
                    recommends.append(recommend)
            except (ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
                logger.error(f"error at {symbols[i]} `analyze_execute`: {e}")
                continue
        
        if recommends:
            final = max(recommends, key=lambda x: x.get("confidence", 0))
            logger.info(f"final recommend:: {final}")
            return final
        logger.info("Analyzer does not recommended any positions")


    def generate_prompt(self, symbols: List, interval: str, limit: int):
        for symbol in symbols:
            ohlcv = self.ohlcvApi.get_ohlcv_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            indicator = Indicator(ohlcv, self.indParams)
            indicators = indicator.getT()
            prompts = self.pm.generate_from(
                ohlcv=ohlcv,
                indicators=indicators,
                ohlcvMeta=OhlcvMeta(symbol=symbol, interval=interval, limit=limit),
                indParams=self.indParams
            )
            ## DB insert 작업 추가
            yield prompts
