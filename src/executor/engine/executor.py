from loguru import logger

from src.executor.engine.analyzer.analyze_executor import AnalyzeExecutor
from src.executor.engine.binance.trade_executor import TradeExecutor

class Executor:
    def __init__(self):
        self.analyzeExecutor = AnalyzeExecutor()
        self.tradeExecutor = TradeExecutor()
    
    def execute(self):
        ohlcvMeta = self._get_analyze_config()
        r = self.analyzeExecutor.analyze_execute(**ohlcvMeta)
        if not r:
            return
        result = self.tradeExecutor.open_execute(**r)
        logger.info(f"result: {result}")

    def _get_analyze_config(self):
        return {
            "symbols": ["BTCUSDT", "ETHUSDT", "XRPUSDT"],
            "interval": "1h",
            "limit": 150
        }