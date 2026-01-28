import asyncio
import json

from src.binance.service.position_event.position_event_service import PositionEventService


def test_add_position_event():
    service = PositionEventService()
    message = json.loads(MESSAGE)
    asyncio.run(service.add_position_event(message))

MESSAGE = """{'e': 'ORDER_TRADE_UPDATE',
	 'T': 1768221016320, 
	 'E': 1768221016320,
	 'o': 
		 {'s': 'BTCUSDT', 
			 'c': 'web_coin_0pyir5jfxq9ipea467151dm', 
			 'S': 'BUY', 
			 'o': 'LIMIT', 
			 'f': 'GTC', 
			 'q': '0.175', 
			 'p': '90755.9', 
			 'ap': '90755.9', 
			 'sp': '0', 
			 'x': 'TRADE', 
			 'X': 'FILLED', 
			 'i': 11624126955, 
			 'l': '0.175', 
			 'z': '0.175', 
			 'L': '90755.9', 
			 'n': '3.1764565', 
			 'N': 'USDT', 
			 'T': 1768221016320, 
			 't': 435875611, 
			 'b': '0', 
			 'a': '0', 
			 'm': true, 
			 'R': false, 
			 'wt': 'CONTRACT_PRICE', 
			 'ot': 'LIMIT', 
			 'ps': 'BOTH', 
			 'cp': false, 
			 'rp': '0', 
			 'pP': false, 
			 'si': 0, 
			 'ss': 0, 
			 'V': 'EXPIRE_MAKER', 
			 'pm': 'NONE', 
			 'gtd': 0, 
			 'er': '0'
		 }
 }""".replace("'", '"')
