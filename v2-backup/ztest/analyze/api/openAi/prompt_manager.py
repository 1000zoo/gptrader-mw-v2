from analyze.api.openAi.prompt_manager.impl.base_prompt_manager import BasePromptManager
from src.common.model.params import IndParams
from src.common.model.base import OhlcvMeta

def test_prompt_manager():
    indParam = IndParams()
    om = OhlcvMeta(symbol="BTCUSDT")
    uk = om.to_dict()
    uk["data"] = [{"qq": 1}]
    print(uk)
    kwargs = {
        "system_kwargs": indParam.to_dict(),
        "user_kwargs": uk
    }
    pm = BasePromptManager()
    a = pm.generate_prompts(**kwargs)
    print(a.user_prompt)
