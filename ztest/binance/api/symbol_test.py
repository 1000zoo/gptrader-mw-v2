from src.binance.api.symbol.symbol_api import SymbolApi



def test_symbol_information():
    symbolApi = SymbolApi()
    res = symbolApi.get_symbol_info('BTCUSDT')
    print(res)


def test_symbols_information():
    symbolApi = SymbolApi()
    res = symbolApi.get_symbols_info(["BTCUSDT", "ETHUSDT", "XRPUSDT"])
    print(res)