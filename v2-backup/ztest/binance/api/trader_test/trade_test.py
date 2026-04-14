from src.binance.api.trader.trade_api import TradeApi


api = TradeApi()

def test_close_market():
    # _pre_settings()

    api.close_position("ETHUSDT")

def test_open_market():
    _open_market("BTCUSDT", side="SELL")

def _open_market(symbol="BTCUSDT", side="BUY"):
    price = api._get_ticker_price(symbol=symbol)

    high = price + price * 0.001
    low = price - price * 0.001

    if side == "BUY":
        tp = high
        sl = low
    else:
        tp = low
        sl = high

    r = api.open_market_position(
        symbol=symbol,
        side=side,
        percent=0.15,
        leverage=11,
        tp=tp,
        sl=sl
    )
    print(r)

def _pre_settings():
    l = [
        {"symbol": "BTCUSDT", "side": "BUY"},
        {"symbol": "XRPUSDT", "side": "SELL"},
        {"symbol": "ETHUSDT", "side": "BUY"}
    ]
    for _l in l:
        _open_market(**_l)

def algo_test():
    p = api.make_algo_order("BTCUSDT", "BUY", 90000.0, 85555.5)
    print(p)

def sol_test():
    THRESHOLD = 0.5
    confidence = 0.65
    leverage = int(5 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (15 - 5))
    percent_of_balance = round(0.2 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (0.5 - 0.2), 2)

    params = {
        'symbol': "SOLUSDT",
        "side": "BUY",
        "percent": percent_of_balance,
        "leverage": leverage,
        "tp": 129.20000000,
        "sl": 122.75000000
    }
    p = api.open_market_position(**params)
    print(p)

    pass