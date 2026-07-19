from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from src.domain.indicator import IndicatorSet, IndicatorValue
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.strategy import StrategyContext
from src.infrastructure.llm.prompt_builder import PromptBuilder, PromptMessage


def make_context() -> StrategyContext:
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    opened_at = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    candle = Candle(
        symbol=symbol,
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        volume=Decimal("12.5"),
    )
    market = MarketSnapshot(candles=(candle,))
    indicators = IndicatorSet(
        symbol=symbol,
        timeframe=timeframe,
        measured_at=candle.closed_at,
        values=(
            IndicatorValue(
                name="rsi",
                value=Decimal("52.1"),
                measured_at=candle.closed_at,
                parameters={"window": 14},
            ),
        ),
    )
    return StrategyContext(
        market=market,
        indicators=indicators,
        metadata={"regime": "trend"},
    )


def test_prompt_builder_builds_deterministic_messages():
    messages = PromptBuilder().build(
        strategy_name="Momentum LLM",
        instructions="Return strict JSON only.",
        context=make_context(),
    )

    assert messages[0] == PromptMessage(
        role="system",
        content=(
            "You are evaluating the Momentum LLM trading strategy. "
            "Return strict JSON only."
        ),
    )
    assert messages[1].role == "user"
    payload = json.loads(messages[1].content)
    assert payload == {
        "indicators": {
            "rsi.window_14": {
                "measured_at": "2026-05-24T00:01:00+00:00",
                "parameters": {"window": "14"},
                "value": "52.1",
            }
        },
        "latest_candle": {
            "close": "105",
            "closed_at": "2026-05-24T00:01:00+00:00",
            "high": "110",
            "low": "90",
            "open": "100",
            "opened_at": "2026-05-24T00:00:00+00:00",
            "volume": "12.5",
        },
        "metadata": {"regime": "trend"},
        "symbol": "BTCUSDT",
        "timeframe": "1m",
    }

    with pytest.raises(AttributeError):
        messages[0].content = "changed"

