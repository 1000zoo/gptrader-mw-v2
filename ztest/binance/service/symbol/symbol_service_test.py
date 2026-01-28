import asyncio

from src.binance.service.symbol.symbol_service import SymbolService

service = SymbolService()

def test_add_symbol():
    asyncio.run(service.add_symbol("BTCUSDT"))

def test_add_symbols():
    asyncio.run(service.add_symbol(["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]))

def test_add_wrong_symbols():
    asyncio.run(service.add_symbol(["BTCUSDT", "!@#ETHUSDTT", "XRPUSDT"]))

def test_find_symbols():
    symbol_list = asyncio.run(service.find_use_symbols())
    print([symbol.symbol_id for symbol in symbol_list])

def test_get_update_today_n():
    s = asyncio.run(service.get_update_today_n("BTCUSDT"))
    print(s)