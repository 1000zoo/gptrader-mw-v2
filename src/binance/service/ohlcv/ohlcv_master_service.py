from typing import List

from loguru import logger

from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.service.ohlcv.ohlcv_summary_service import OhlcvSummaryService
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.binance.vo.ohlcv.summary_default import OhlcvSummaryVo
from src.binance.vo.ohlcv.summary_filter import OhlcvSummaryFilterVo


class OhlcvMasterService:
    def __init__(self):
        self.ohlcvService = OhlcvService()
        self.ohlcvSummaryService = OhlcvSummaryService()


    async def ohlcv_candle_load(self, vo: DefaultOhlcvVo) -> List[DefaultOhlcvVo]:
        candle_data : List[DefaultOhlcvVo] = await self.ohlcvService.load_ohlcv(
            symbol_name=vo.symbol_id,
            interval=vo.c_interval,
            limit=vo.c_limit,
            batch_id=vo.batch_id
        )
        candle_data.sort(key=lambda x: x.ts)
        start_candle = candle_data[0]
        summary : OhlcvSummaryVo = await self.ohlcvSummaryService.load_ohlcv_summary(
            symbol_name=start_candle.symbol_id,
            interval=start_candle.c_interval,
            limit=start_candle.c_limit,
            batch_id=start_candle.batch_id,
            start_time=start_candle.ts
        )
        logger.info(f"candle load success => {summary}")
        return candle_data

    async def only_fetch_candle(self, vo: OhlcvFilterVo) -> List[DefaultOhlcvVo]:
        candle_data : List[DefaultOhlcvVo] = await self.ohlcvService.fetch_ohlcv(
            symbol=vo.symbol_id,
            interval=vo.c_interval,
            limit=vo.c_limit,
        )
        return candle_data

    async def fetch_from_summary(self, vo: OhlcvSummaryFilterVo) -> List[DefaultOhlcvVo]:
        summary_vos : List[OhlcvSummaryVo] = await self.ohlcvSummaryService.find_ohlcv_summary(vo)
        if len(summary_vos) > 1:
            raise Exception("하나여야함") # TODO 나중에 common.exception에 추가
        summary_vo = summary_vos[0]
        return await self.ohlcvService.fetch_ohlcv(
            symbol=summary_vo.symbol_id,
            interval=summary_vo.c_interval,
            limit=summary_vo.c_limit,
            start_time=summary_vo.start_ts
        )

    async def delete_candles(self) -> int:
        count = await self.ohlcvService.count_total_candles()
        if count <= 0:
            return 0

        chunk_size = 10000
        deleted_total = 0

        while deleted_total < count:
            limit = min(chunk_size, count - deleted_total)
            deleted = await self.ohlcvService.delete_candles(limit=limit, symbol="%")
            if deleted <= 0:
                break
            deleted_total += deleted

        return deleted_total


