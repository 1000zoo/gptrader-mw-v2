from src.binance.api.trader.account_api import AccountApi
from ztest.test_helper import pretty_printer

api = AccountApi()

def test_balance():
    r = api.get_balance()
    pretty_printer(r)

def test_account():
    r = api.get_account()
    pretty_printer(r)

def test_usdt_balance():
    f = api.get_usdt_balance()
    print(f)

def test_current_positions():
    r = api.get_current_positions()
    pretty_printer(r)

def test_all_orders():
    r = api.get_all_orders("BTCUSDT")