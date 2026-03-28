from typing import Optional

from loguru import logger

from src.binance.api.trader.trade_api import TradeApi
from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto
from src.common.config import THRESHOLD
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException


def _normalize_confidence(confidence: Optional[float]) -> Optional[float]:
    if confidence is None:
        return None
    if confidence > 1:
        return confidence / 100
    return confidence


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if not side:
        return None
    side_upper = side.upper()
    if side_upper in {"LONG", "BUY"}:
        return "BUY"
    if side_upper in {"SHORT", "SELL"}:
        return "SELL"
    if side_upper == "NONE":
        return None
    return None


class TradeService:
    def __init__(self):
        self.tradeApi = TradeApi()

    async def open_from_analyze(self, dto: TradeExecuteDto):
        confidence = _normalize_confidence(dto.confidence)
        if confidence is None:
            logger.info(f"confidence is missing: {dto.symbol_id}")
            raise InvalidRequestException("Confidence is required for trade execution.")

        if confidence < THRESHOLD:
            logger.info(f"confidence is so low: {dto.symbol_id}, {confidence}")
            raise InvalidRequestException("Confidence is below the execution threshold.")

        side = _normalize_side(dto.side)
        if not side:
            logger.info(f"invalid side: {dto.symbol_id}, {dto.side}")
            raise InvalidRequestException("Trade side is invalid.")

        entry_price = dto.entry_price
        if dto.tp is None or dto.sl is None:
            logger.info(f"tp/sl is missing: {dto.symbol_id}, tp={dto.tp}, sl={dto.sl}")
            raise InvalidRequestException("TP/SL values are required for trade execution.")

        leverage = int(5 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (15 - 5))
        percent_of_balance = round(0.2 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (0.5 - 0.2), 2)

        if percent_of_balance <= 0:
            raise InvalidRequestException("Position size is zero after regime policy.")

        try:
            response = self.tradeApi.open_market_position(
                symbol=dto.symbol_id,
                side=side,
                percent=percent_of_balance,
                leverage=leverage,
                tp=dto.tp,
                sl=dto.sl,
            )
        except ExternalApiError as e:
            logger.error(f"error at `open_from_analyze` {dto.symbol_id}:: {e}")
            raise ExternalApiError("Failed to open market position.") from e
        if not response or response.get("error") or response.get("success") is False:
            raise ExternalApiError("Market position response indicated failure.")

        entry_order_id=response.get("main_response", {}).get("clientOrderId"),

        logger.bind(
            run_id=dto.batch_id,
            symbol=dto.symbol_id,
            entry_price=entry_price,
            action_id=None,
            job_id=dto.batch_id,
            order_id=entry_order_id,
        ).info("trade_fill created (OPEN)")
        return response

    def cancel_open_orders(self, symbol: str):
        try:
            response = self.tradeApi.cancel_open_orders(symbol)
        except ExternalApiError as e:
            logger.error(f"error at `service.cancel_all_open_orders`: {e}")
            raise ExternalApiError("Failed to cancel open orders.") from e
        if response is None or response.get("error") or response.get("success") is False:
            raise ExternalApiError("Cancel open orders response indicated failure.")
        return response

    def close_position(self, symbol: str):
        try:
            return self.tradeApi.close_position(symbol)
        except ExternalApiError as e:
            logger.error(f"error at `service.close_position`: {e}")
            raise ExternalApiError("Failed to close position.") from e
