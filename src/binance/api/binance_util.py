import os

from src.binance.constants.url import *

def isTest():
    temp = os.getenv("ISTEST")
    return temp != 'False'

def get_key():
    if isTest():
        key = os.getenv("BINANCE_TEST_API_KEY")
        secret = os.getenv("BINANCE_TEST_SECRET_KEY")
    else:
        key = os.getenv("BINANCE_API_KEY")
        secret = os.getenv("BINANCE_SECRET_KEY")
    return key, secret

def get_settings():
    key, secret = get_key()
    url = BINANCE_TESTNET if isTest() else BINANCE_MAINNET
    return key, secret, url

def get_ws_settings():
    key, secret, url = get_settings()
    ws_url = BINANCE_WS_TEST if isTest() else BINANCE_WS_MAIN
    return key, secret, url, ws_url