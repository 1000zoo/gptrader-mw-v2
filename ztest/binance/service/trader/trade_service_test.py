from src.binance.service.trader.trade_service import TradeService
from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto

def test_open_position():
    dto = TradeExecuteDto(
        symbol_id="BTCUSDT",
        side="long",
        entry_price=94734.5,
        tp=95000,
        sl=93000,
        confidence=0.7
    )
    service = TradeService()

    service.open_from_analyze(dto)