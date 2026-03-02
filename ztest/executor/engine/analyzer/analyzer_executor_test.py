from src.executor.engine.analyzer.analyze_executor import AnalyzeExecutor
from src.analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager
from src.common.model.params import IndParams
from ztest.test_helper import pretty_printer

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
INTERVAL = "1h"
LIMIT = 120

def test():
    indParams = IndParams()
    indParams.tail = 1
    ae = AnalyzeExecutor(indParams=indParams)
    k = ae.analyze_execute(SYMBOLS, INTERVAL, LIMIT)
    pretty_printer(k)