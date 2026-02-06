import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from src.common.logger.logger_config import setup_logging
from src.common.exception.exception_handler import handle_top_level_exception
from src.binance.ws.listener.position_listener import PositionListener

async def _main():
    while True:
        pl = PositionListener()
        try:
            await pl.start()
        except Exception as e:
            logger.exception(f"[MAIN] PositionListener crashed, restarting in 3s: {e}")
            await handle_top_level_exception("websockets", "PositionListener.start", e)
            await asyncio.sleep(3)

if __name__ == '__main__':
    load_dotenv()


    LOG_DIR = os.getenv("LOG_DIR")
    LOG_LEVEL = os.getenv("LOG_LEVEL")

    setup_logging(app_name="websocket", log_dir=LOG_DIR, level=LOG_LEVEL)

    asyncio.run(_main())
