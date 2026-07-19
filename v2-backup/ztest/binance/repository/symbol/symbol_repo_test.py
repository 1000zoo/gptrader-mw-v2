import asyncio

from src.binance.vo.symbol.default import DefaultSymbolVo
from src.binance.repository.symbol.symbol_repo import SymbolRepository

def test_insert():
    
    vo = DefaultSymbolVo(symbol_id="TEST_USDT_2", attr1='N')
    rep = SymbolRepository()

    asyncio.run(rep.insert_symbol(vo))
