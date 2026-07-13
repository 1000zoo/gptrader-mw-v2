import asyncio

from src.binance.executor.symbol.symbol_executor import SymbolExecutor

def test_get_n():
    async def _inner():
        executor = SymbolExecutor()
        symbol_list = await executor.get_symbol_list()

        for symbol in symbol_list:
            n = await executor.get_today_n(symbol)
            print(n)

    asyncio.run(_inner())
