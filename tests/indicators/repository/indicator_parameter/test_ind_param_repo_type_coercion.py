import asyncio
from decimal import Decimal

from src.common.model.params import IndParams
from src.indicators.repository.indicator_parameter.indParam_repo import IndicatorParamRepository
from src.indicators.vo.indicator_parameter.default import DefaultIndicatorParamsVo
import src.indicators.repository.indicator_parameter.indParam_repo as repo_module


def test_select_params_coerces_decimal_numeric_fields_to_float(monkeypatch):
    async def fake_common_select(table, vo, vo_cls):
        params = IndParams(name="default_2")
        params.bollinger_k = Decimal("2.0000")
        params.keltner_m = Decimal("1.5000")
        return [params]

    monkeypatch.setattr(repo_module, "common_select", fake_common_select)

    repo = IndicatorParamRepository()
    result = asyncio.run(repo.select_params(DefaultIndicatorParamsVo(name="default_2")))

    assert isinstance(result.bollinger_k, float)
    assert isinstance(result.keltner_m, float)
    assert result.bollinger_k == 2.0
    assert result.keltner_m == 1.5
