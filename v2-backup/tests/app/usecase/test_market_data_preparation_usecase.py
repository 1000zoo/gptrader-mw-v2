import asyncio

from src.app.usecase.market_data_preparation_usecase import PrepareDataDto, MarketDataPreparationUseCase


def test_prepare_data():
    dto_list = [
        PrepareDataDto(symbol_id="BTCUSDT", interval="1m", limit=150, params_name="default_2"),
        PrepareDataDto(symbol_id="BTCUSDT", interval="5m", limit=150, params_name="default_2"),
        PrepareDataDto(symbol_id="BTCUSDT", interval="15m", limit=150, params_name="default_2"),
        PrepareDataDto(symbol_id="BTCUSDT", interval="1h", limit=150, params_name="default_2"),
    ]
    usecase = MarketDataPreparationUseCase()

    k = asyncio.run(usecase.prepare_data(dto_list))
    print(k)
