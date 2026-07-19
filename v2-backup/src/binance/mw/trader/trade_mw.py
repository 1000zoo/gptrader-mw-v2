from fastapi import APIRouter, Depends
from loguru import logger


from src.binance.api.trader.trade_api import TradeApi
from src.analyze.mw.openAi.openAi_util import to_api_response
from src.common.util.base import success_meta, fail_meta
from src.common.model.base import Meta
from src.common.model.request import TradeRequest, TradeCloseRequest
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.invalid_response_exception import InvalidResponseException

router = APIRouter(prefix="/trade")

def _resp_helper(meta: Meta, key: str, item: str):
    return {
        "meta": meta,
        key: item
    }
 
@router.post("/openMarket")
def openMarketPosition(req: TradeRequest, svc=Depends(lambda: TradeSerivce())):
    try:
        resp = svc.open_market(req)
        meta = success_meta()
    except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
        logger.error(f"openMarketPosition error: {e}")
        meta = fail_meta(msg=str(e))
        resp = None
    return _resp_helper(meta, "response", resp)

@router.post("/closeMarket")
def closeMarketPosition(req: TradeCloseRequest, svc=Depends(lambda: TradeSerivce())):
    try:
        resp = svc.close_market(req)
        if resp is None:
            meta = success_meta(msg="position does not exist")
        else:
            meta = success_meta()
    except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
        logger.error(f"closeMarketPosition error: {e}")
        meta = fail_meta(msg=str(e))
        resp = None
    return _resp_helper(meta, "response", resp)

class TradeSerivce():
    def __init__(self):
        self.api = TradeApi()

    def open_market(self, req: TradeRequest):
        r = req.model_dump()
        return self.api.open_market_position(**r)
        
    def close_market(self, req: TradeCloseRequest):
        r = self.api.close_position(symbol=req.symbol)
        return r
    
