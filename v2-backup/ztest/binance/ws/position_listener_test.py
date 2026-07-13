import asyncio

from src.binance.ws.listener.position_listener import PositionListener

def test_start():
    pl = PositionListener()
    asyncio.run(pl.start())