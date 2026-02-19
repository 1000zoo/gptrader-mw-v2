from src.common.model.params import IndParams
from src.indicators.engine.indicator import Indicator
from src.strategy.strategies.models import ALLOWED_INDICATOR_COLUMNS


def _sample_ohlcv(limit: int = 300):
    rows = []
    base_ts = 1700000000000
    price = 100.0
    for i in range(limit):
        price += 0.1
        rows.append(
            {
                "openTime": base_ts + (i * 60_000),
                "open": price - 0.2,
                "high": price + 0.3,
                "low": price - 0.4,
                "close": price,
                "quoteAssetVolume": 1000.0 + i,
                "takerBuyBaseAsset": 500.0,
                "takerBuyQuoteAsset": 500.0,
                "numberOfTrades": 100 + i,
            }
        )
    return rows


def test_allowed_columns_matches_indicator_get_all_keys():
    indicator = Indicator(_sample_ohlcv(), IndParams())
    keys = set(indicator.get_all().keys())
    assert keys == ALLOWED_INDICATOR_COLUMNS
