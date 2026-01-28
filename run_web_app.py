import os

from fastapi import FastAPI
from dotenv import load_dotenv

from src.analyze.mw.openAi import openAi_mw
from src.binance.mw.symbol import symbol_mw
from src.binance.mw.ohlcv import ohlcv_mw
from src.binance.mw.trader import account_mw
from src.binance.mw.trader import trade_mw
from src.indicators.mw.indicator import indicator_mw
from src.ops.mw import ops_mw
from src.common.logger.logger_config import setup_logging, install_fastapi_middleware

def create_app():
    app = FastAPI(title="gptrader")
    app.include_router(symbol_mw.router, prefix="/api/v1")
    app.include_router(ohlcv_mw.router, prefix="/api/v1")
    app.include_router(indicator_mw.router, prefix="/api/v1")
    app.include_router(openAi_mw.router, prefix="/api/v1")
    app.include_router(account_mw.router, prefix="/api/v1/trader")
    app.include_router(trade_mw.router, prefix="/api/v1/trader")
    app.include_router(ops_mw.router, prefix="/api/v1")

    return app

load_dotenv(dotenv_path=".env")

LOG_DIR = os.getenv("LOG_DIR")
LOG_LEVEL = os.getenv("LOG_LEVEL")

setup_logging(app_name="gptrader", log_dir=LOG_DIR, level=LOG_LEVEL)

app = create_app()

install_fastapi_middleware(app)
