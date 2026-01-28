import os
import math, hmac, hashlib, httpx, time
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN

from loguru import logger
from typing import Tuple, Dict, Any

from binance.um_futures import UMFutures
from binance.error import ClientError

from src.binance.api.symbol.symbol_api import SymbolApi
from src.binance.api.trader.account_api import AccountApi
from src.binance.api.trader.trade_util import cal_quantity
from src.binance.api.binance_util import get_settings
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException

class TradeApi:
    def __init__(self):
        self.key, self.secret, self.url = get_settings()
        self.client = UMFutures(key=self.key, secret=self.secret, base_url=self.url)
        self.symbolApi = SymbolApi()
        self.accountApi = AccountApi()

    def _get_ticker_price(self, symbol: str) -> float:
        try:
            return float(self.client.ticker_price(symbol)["price"])
        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `get ticker price`: {e}")
            raise ExternalApiError("Failed to fetch ticker price.") from e

    def _get_precision_step_size(self, symbol: str, use_market_step: bool = False) -> Tuple[int, float]:
        try:
            data = self.symbolApi.get_symbol_info(symbol_name=symbol)
            if not data:
                raise InvalidResponseException("Symbol info response is empty.")
            symbol_info = data[0]

            if use_market_step:
                step_str = symbol_info.get("marketStepSize") or symbol_info.get("stepSize")
            else:
                step_str = symbol_info.get("stepSize") or symbol_info.get("marketStepSize")
            if not step_str:
                raise InvalidResponseException("Symbol step size is missing.")

            step_dec = Decimal(str(step_str))

            precision = max(-step_dec.normalize().as_tuple().exponent, 0)
            return precision, float(step_dec)

        except (ClientError, KeyError, TypeError, ValueError, InvalidResponseException) as e:
            logger.error(f"error at `_get precision step size`: {e}")
            raise ExternalApiError("Failed to determine symbol precision/step size.") from e


    def _set_sl_tp(self, symbol: str, sl: float, tp: float):
        try:
            data = self.symbolApi.get_symbol_info(symbol_name=symbol)
            if not data:
                raise InvalidResponseException("Symbol info response is empty.")
            symbol_info = data[0]
            tick_size = symbol_info.get("tickSize")
            if not tick_size:
                raise InvalidResponseException("Symbol tick size is missing.")
            tick_size_dec = Decimal(str(tick_size))
            precision = max(-tick_size_dec.normalize().as_tuple().exponent, 0)
            return (
                float(Decimal(str(sl)).quantize(Decimal("1").scaleb(-precision), rounding=ROUND_DOWN)),
                float(Decimal(str(tp)).quantize(Decimal("1").scaleb(-precision), rounding=ROUND_DOWN)),
            )
        except (ClientError, KeyError, TypeError, ValueError, InvalidResponseException) as e:
            logger.error(f"error at `_set_sl_tp: {e}")
            raise ExternalApiError("Failed to set SL/TP values.") from e

    def _get_position_quantity(self, symbol: str, max_retries: int = 3, delay_s: float = 0.2) -> float:
        for attempt in range(max_retries):
            positions = self.accountApi.get_current_positions()
            for position in positions:
                if position.get("symbol") == symbol:
                    qty = abs(float(position.get("positionAmt", 0)))
                    if qty > 0:
                        return qty
            if attempt < max_retries - 1:
                time.sleep(delay_s)
        return 0.0

    def open_market_position(self,
                      symbol: str,
                      side: str,    ## BUY || SELL
                      percent: float,
                      leverage: float,
                      tp: float,
                      sl: float):
        try:
            balance = self.accountApi.get_usdt_balance()
            price = self._get_ticker_price(symbol=symbol)
            precision, step_size = self._get_precision_step_size(symbol=symbol, use_market_step=True)
            quantity = cal_quantity(
                price=price,
                balance=balance,
                percent=percent,
                leverage=leverage,
                step_size=step_size,
                precision=precision
            )
            leverage = int(round(leverage))
            self.client.change_leverage(symbol=symbol, leverage=leverage)
            order_params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": quantity,
                "positionSide": "BOTH",
            }
            logger.info(f"order params:: {order_params}")
            main_response = self.client.new_order(**order_params)

            sl, tp = self._set_sl_tp(symbol, sl, tp)
            position_qty = self._get_position_quantity(symbol=symbol)
            if position_qty <= 0:
                position_qty = quantity

            tp_response, sl_response = self.make_algo_order(
                symbol=symbol,
                entry_side=side,
                tp=tp,
                sl=sl,
                position_side="BOTH",
                working_type="CONTRACT_PRICE"
            )

            return {
                "main_response": main_response or {"clientOrderId": None},
                "tp_response": tp_response or {"clientOrderId": None},
                "sl_response": sl_response or {"clientOrderId": None}
            } ## 여기서 세 주문의 id (origin id, tp id, sl id 반환하여 저장하도록 로직 추가)

        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `open_market_position:: {e}")
            raise ExternalApiError("Failed to open market position.") from e

    def close_position(self, symbol: str):
        try:
            positions = self.accountApi.get_current_positions()
            position = None
            for p in positions:
                if p["symbol"] == symbol:
                    position = p
                    break
            if not position:
                logger.info(f"there is no position {symbol}")
                return
            
            qty = abs(float(position["positionAmt"]))
            side = "SELL" if float(position["positionAmt"]) >= 0 else "BUY"

            self.client.cancel_open_orders(symbol=symbol)

            res = self.client.new_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty,
                reduceOnly=True,
                positionSide="BOTH",
            )

            return res
        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `close_position`: {e}")
            raise ExternalApiError("Failed to close position.") from e
    
    def cancel_open_orders(self, symbol: str):
        try:
            r = self.client.cancel_open_orders(symbol=symbol)
            return r
        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `cancel_open_orders`: {e}")
            raise ExternalApiError("Failed to cancel open orders.") from e
        
    
    def close_all_position(self):
        try:
            positions = self.accountApi.get_current_positions()
            for p in positions:
                symbol = p["symbol"]
                self.close_position(symbol=symbol)
            return {"success": True}
        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `close_all_position`: {e}")
            raise ExternalApiError("Failed to close all positions.") from e

    def cancel_all_open_orders(self):
        try:
            positions = self.accountApi.get_current_positions()
            for p in positions:
                symbol = p["symbol"]
                self.cancel_open_orders(symbol=symbol)
            return {"success": True}
        except (ClientError, KeyError, TypeError, ValueError) as e:
            logger.error(f"error at `cancel_all_open_orders`: {e}")
            raise ExternalApiError("Failed to cancel all open orders.") from e

    ## 추후에 통합 api 클래스로 변경 (symbol, trade, ohlcv ...)
    def fapi_signed_post(self, path:str, params: Dict[str, Any]):
        params["timestamp"] = int(time.time() * 1000)

        query = urlencode(params, doseq=True)
        signature = hmac.new(
            self.secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        base_url = f"{self.url}{path}"
        logger.info(f"fapi post:: {base_url}, params: {params}")
        url = f"{base_url}?{query}&signature={signature}"

        headers = {"X-MBX-APIKEY": self.key}
        r = httpx.post(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()


    def make_algo_order(
        self,
        symbol: str,
        entry_side: str,
        tp: float,
        sl: float,
        position_side: str = "BOTH",
        working_type: str = "CONTRACT_PRICE",
    ):
        exit_side = "SELL" if entry_side.upper() == "BUY" else "BUY"

        common = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": exit_side,
            "closePosition": "true",  # ✅ 핵심: qty 없이 “전량 청산”
            "positionSide": position_side,
            "workingType": working_type,
        }

        tp_res = self.fapi_signed_post("/fapi/v1/algoOrder", {
            **common,
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": tp,
        })

        sl_res = self.fapi_signed_post("/fapi/v1/algoOrder", {
            **common,
            "type": "STOP_MARKET",
            "triggerPrice": sl,
        })

        return tp_res, sl_res
