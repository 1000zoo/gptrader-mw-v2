from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.indicators.engine.calculator import Calculator


def __load_data(limit=5):
    api = OHLCVApi()
    return api.get_ohlcv_klines("BTCUSDT", "1h", limit)

def __load_cal(limit=5):
    d = __load_data(limit=limit)
    return Calculator(d)

def test_calculator_init():
    api = OHLCVApi()
    data = api.get_ohlcv_klines("BTCUSDT", "1h", 5)
    c = Calculator(data)
    print(c.df)

def test_calculator_ma():
    api = OHLCVApi()
    data = api.get_ohlcv_klines("BTCUSDT", "1h", 15)
    c = Calculator(data)
    print(c.cal_ma(window=5))

def test_calculator_bollinger():
    c = __load_cal(limit=30)
    print(c.bollinger())

def test_calculator_tr():
    c = __load_cal()
    print(c.true_range())

def test_calculator_dmiadx():
    c = __load_cal(limit=30)
    print(c.dmi_adx())

def test_calculator_stkd():
    c = __load_cal(limit=50)
    print(c.stochastic_kd())

def test_calculator_cci():
    c = __load_cal(limit=50)
    print(c.cci())

def test_calculator_roc():
    c = __load_cal(limit=50)
    print(c.roc())

def test_calculator_momentum():
    c = __load_cal(limit=50)
    print(c.momentum())

def test_calculator_mfi():
    c = __load_cal(limit=50)
    print(c.mfi())

def test_calculator_vwap():
    c = __load_cal(limit=50)
    print(c.vwap())

def test_calculator_donchian():
    c = __load_cal(limit=50)
    print(c.donchian())

def test_calculator_keltner():
    c = __load_cal(limit=50)
    print(c.keltner())

def test_calculator_lrs():
    c = __load_cal(limit=50)
    print(c.linear_regression_slope())

def test_calculator_score():
    c = __load_cal(limit=50)
    print(c.compute_composite_score())
