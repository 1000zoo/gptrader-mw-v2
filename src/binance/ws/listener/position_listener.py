import asyncio
import json
from typing import Dict

import websockets
from binance.error import ClientError
from binance.um_futures import UMFutures
from loguru import logger
from websockets.exceptions import WebSocketException

from src.binance.api.binance_util import get_ws_settings
from src.binance.ws.handler.event_filter import EventFilter
from src.common.exception.external_api_error import ExternalApiError
from src.ops.service.slack.slack_service import SlackService


class PositionListener:
    def __init__(self):
        key, secret, url, ws_url = get_ws_settings()
        self.ws_url = ws_url
        self.client = UMFutures(key=key, secret=secret, base_url=url)
        self.listen_key = None
        self.error_count = 0
        self.eventFilter = EventFilter()
        self.slack_service = SlackService()

    async def start(self):
        resp = self.client.new_listen_key()
        self.listen_key = resp["listenKey"]
        asyncio.create_task(self._keepalive())
        while True:
            url = f"{self.ws_url}/{self.listen_key}"
            try:
                async with websockets.connect(url) as ws:
                    logger.info("[WS] Connected")
                    self.error_count = 0
                    async for message in ws:
                        m = json.loads(message)
                        await self._event_handler(m)
            except (WebSocketException, json.JSONDecodeError, KeyError, TypeError, ClientError) as e:
                logger.error(f"[WS] error at `start`: {e}")
                self.error_count += 1
                if self.error_count > 3:
                    raise ExternalApiError("Websocket connection failed repeatedly.") from e

    async def _event_handler(self, message: Dict):
        await self.slack_service.send_message("account_event", f"message: {message}")
        return await self.eventFilter.filter(message=message)
    
    def __filter_message(self, message: Dict):
        if message["e"] == 'ORDER_TRADE_UPDATE':
            order = message["o"]
            ot = order["ot"]
            x = order["X"]
            if ot in ('TAKE_PROFIT_MARKET', 'STOP_MARKET') and x == 'FILLED':
                logger.info(f"message:: {message}")
                return True
        return False

    async def _keepalive(self):
        while True:
            try:
                await asyncio.sleep(30 * 60)
                resp = self.client.renew_listen_key(self.listen_key)
                lk = resp["listenKey"]
                self.listen_key = lk
                logger.info(f"[WS] keepalive success: {lk}")
            except (WebSocketException, ClientError, KeyError, TypeError) as e:
                logger.error(f"[WS] keepalive error {e}")
                continue
