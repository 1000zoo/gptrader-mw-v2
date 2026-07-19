import httpx

from src.common.model.request import AnalyzeRequest
from src.common.model.base import Prompts
from src.analyze.api.openAi.openAi_api import OpenAiApi
from analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager
from src.indicators.engine.indicator import Indicator
from src.common.model.params import IndParams
from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.common.model.base import OhlcvMeta

test_json = """
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "position": "long | short | wait",
  "entry_price": 1234.56,
  "take_profit": 1300.00,
  "stop_loss": 1200.00,
  "confidence": 0.0,
  "reason": "short technical explanation"
}
"""

def test_chat():
    prompts = Prompts(system_prompt=f"give response {test_json}, it is test", user_prompt="hello")
    api = OpenAiApi(prompts)
    a = api.chat()
    print(a)


def test_indicator_prompt():
    pm = BasePromptManager()
    params = IndParams()
    bApi = OHLCVApi()
    symbol = "BTCUSDT"
    interval = "1h"
    limit = 150
    ohlcv = bApi.get_ohlcv_klines(symbol, interval=interval, limit=limit)
    indicators = Indicator(ohlcv=ohlcv, indParams=params)
    kwargs = {
        "system_kwargs": params.to_dict(),
        "user_kwargs": {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
            "data": indicators.getT()
        }
    }
    prompts = pm.generate_prompts(**kwargs)
    
    openAiApi = OpenAiApi()
    a = openAiApi.chat(prompts)
    print(a)


def test_fast_api():
    pm = BasePromptManager()
    params = IndParams()
    bApi = OHLCVApi()
    symbol = "BTCUSDT"
    interval = "1h"
    limit = 150
    ohlcv = bApi.get_ohlcv_klines(symbol, interval=interval, limit=limit)
    indicators = Indicator(ohlcv=ohlcv, indParams=params)
    indicators = indicators.getT()

    ohlcvMeta = OhlcvMeta(symbol=symbol, interval=interval, limit=limit)
    
    req = AnalyzeRequest(
        ohlcvMeta=ohlcvMeta,
        ohlcv=ohlcv,
        indicators=indicators,
        indParams=params
    )

    url = "http://0.0.0.0:8080/api/v1/analyze/"

    res = httpx.post(url=url, json=req.model_dump(), timeout=100)
    print(res.json())

    