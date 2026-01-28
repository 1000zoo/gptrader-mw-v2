from enum import Enum

class KeyEnum(Enum):
    EVENT = "e"
    EVENT_TIME = "E"
    TRANSACTION_TIME = "T"
    ORDER_INFO = "o"
    SYMBOL = "s"
    CLIENT_ORDER_ID = "c"
    SIDE = "S"
    ORDER_TYPE = "o"        # MARKET, LIMIT ?
    EXECUTION_TYPE = "x"    # New, Trade, ...
    ORDER_STATUS = "X"      # Filled, New, Canceled ...
    ORIGIN_ORDER_TYPE = "ot"# TAKE_PROFIT_MARKET, STOP_MARKET ...

class EventEnum(Enum):
    ORDER_TRADE_UPDATE = "ORDER_TRADE_UPDATE"
