from loguru import logger

from src.common.config import THRESHOLD

from src.binance.api.trader.trade_api import TradeApi
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException


class TradeExecutor:
    def __init__(self):
        self.tradeApi = TradeApi()

    def open_execute(self,
                     symbol: str,
                     side: str,
                     entry_price: float,
                     tp: float,
                     sl: float,
                     confidence: float,
                     **kwargs):
        if confidence < THRESHOLD:
            logger.info(f"confidence is so low: {symbol}, {confidence}")
            raise InvalidRequestException("Confidence is below the execution threshold.")
        leverage = int(5 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (15 - 5))
        percent_of_balance = round(0.2 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (0.5 - 0.2), 2)

        side = side.upper()
        side = "BUY" if side == "LONG" else "SELL" if side == "SHORT" else None
        if not side:
            logger.info(f"invalide side:: {symbol}, {side}")
            raise InvalidRequestException("Trade side is invalid.")
        
        try:
            r = self.tradeApi.open_market_position(
                symbol=symbol,
                side=side,
                percent=percent_of_balance,
                leverage=leverage,
                tp=tp,
                sl=sl
            )
        except ExternalApiError as e:
            logger.error(f"error at `open_execute` {symbol}:: {e}")
            raise

        return r
