from decimal import Decimal

import pytest

from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyResult
from src.infrastructure.llm.response_parser import (
    LLMResponseParseError,
    ResponseParser,
)


def test_response_parser_converts_json_to_strategy_result():
    result = ResponseParser().parse(
        strategy_name="Momentum LLM",
        raw_text=(
            '{"direction":"long","confidence":"0.82",'
            '"reasons":[{"code":"trend","message":"Momentum confirmed",'
            '"metadata":{"source":"rsi"}}],'
            '"metadata":{"model":"test-model"}}'
        ),
    )

    assert isinstance(result, StrategyResult)
    assert result.name == "Momentum LLM"
    assert result.signal.direction is SignalDirection.LONG
    assert result.signal.confidence == Decimal("0.82")
    assert result.signal.reasons[0].code == "trend"
    assert result.signal.reasons[0].message == "Momentum confirmed"
    assert result.signal.reasons[0].metadata["source"] == "rsi"
    assert result.signal.metadata["model"] == "test-model"


@pytest.mark.parametrize(
    "raw_text",
    [
        "not-json",
        '{"confidence":"0.82"}',
        '{"direction":"sideways","confidence":"0.82"}',
        '{"direction":"long","confidence":"1.82"}',
        '{"direction":"long","confidence":"0.82","reasons":[{"code":""}]}',
    ],
)
def test_response_parser_translates_invalid_output(raw_text):
    with pytest.raises(LLMResponseParseError):
        ResponseParser().parse(strategy_name="Momentum LLM", raw_text=raw_text)

