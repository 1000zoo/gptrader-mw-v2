from fastapi import APIRouter, Depends
from loguru import logger


from src.binance.api.trader.account_api import AccountApi
from src.common.util.base import success_meta, fail_meta
from src.common.model.base import Meta
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.invalid_response_exception import InvalidResponseException

router = APIRouter(prefix="/account")

def _resp_helper(meta: Meta, key: str, item: str):
    return {
        "meta": meta,
        key: item
    }

@router.get("/onPosition")
def onPosition(symbol: str, svc=Depends(lambda: AccountService())):
    try:
        onP = svc.on_position(symbol)
        meta = success_meta()
    except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
        logger.error(f"onPosition error: {e}")
        onP = None
        meta = fail_meta(msg=str(e))
    return {
        "meta": meta,
        "onPosition": onP
    }

@router.get("/balance")
def getBalance(asset: str = "USDT", svc=Depends(lambda: AccountService())):
    asset = asset.upper()
    try:
        b = svc.get_balance(asset)
        meta = success_meta()
    except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
        logger.error(f"getBalance error: {e}")
        b = {}
        meta = fail_meta(msg=str(e))
    return _resp_helper(meta, "balance", b)

@router.get("/info")
def getAccountInfo(asset: str = "USDT", svc=Depends(lambda: AccountService())):
    asset = asset.upper()
    try:
        info = svc.get_account_info(asset)
        meta = success_meta()
    except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
        logger.error(f"getAccountInfo error: {e}")
        info = {}
        meta = fail_meta(msg=str(e))
    return _resp_helper(meta, "accountInfo", info)

class AccountService():
    def __init__(self):
        self.api = AccountApi()
    
    def on_position(self, symbol):
        if not symbol:
            raise InvalidRequestException("Symbol is required.")
        positions = self.api.get_current_positions()
        for position in positions:
            if position["symbol"] == symbol:
                return True
        return False

    def get_balance(self, asset: str):
        if not asset:
            raise InvalidRequestException("Asset is required.")
        assets = self.api.get_balance()
        for a in assets:
            if a["asset"] == asset:
                return a
        raise DataNotFoundException(f"Balance not found for asset {asset}.")
    
    def get_account_info(self, asset: str):
        if not asset:
            raise InvalidRequestException("Asset is required.")
        info = self.api.get_account()
        assets = info.get("assets")
        if assets is None:
            raise InvalidResponseException("Account info response missing assets.")
        for i in assets:
            if i["asset"] == asset:
                return i
        raise DataNotFoundException(f"Account info not found for asset {asset}.")
