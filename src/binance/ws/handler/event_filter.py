from typing import Dict

from loguru import logger

from src.binance.ws.handler.handler.order_event_handler import OrderEventHandler
from src.binance.ws.constants.enums import KeyEnum

class EventFilter:
    def __init__(self):
        self.orderEventHandler = OrderEventHandler()

    async def filter(self, message: Dict):
        logger.info(f"event filter: {message.get(KeyEnum.EVENT.value)}")
        logger.info(f"event:: {message}")
        if message["e"] == 'ORDER_TRADE_UPDATE':
            return await self.orderEventHandler.execute(message)

        if message["e"] == 'ALGO_UPDATE':
            return await self.orderEventHandler.algo_execute(message)

        if message["e"] == 'ACCOUNT_UPDATE':
            return await self.orderEventHandler.account_update(message)
