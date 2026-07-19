# Binance API Manual Test

FastAPI endpoints for checking real Binance USD-M Futures request and response payloads through Postman.

## Run

Install dependencies if needed:

```bash
pip install -r requirements.txt
```

Start the local API:

```bash
uvicorn api_test.binance_api_test_app:app --reload --port 8010
```

Open docs:

```text
http://127.0.0.1:8010/docs
```

## Environment

The app reads `.env.test` from the repository root through `python-dotenv`.

Required for signed/account/order/listen-key calls:

```text
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TEST_API_KEY=...
BINANCE_TEST_API_SECRET=...
```

Recommended for live validation:

```text
BINANCE_TESTNET=true
```

Optional:

```text
BINANCE_BASE_URL=https://fapi.binance.com
BINANCE_TEST_BASE_URL=https://demo-fapi.binance.com
BINANCE_TIMEOUT=10
BINANCE_RECV_WINDOW=5000
BINANCE_RETRY_ATTEMPTS=1
BINANCE_RETRY_DELAY=0
```

## Endpoints

- `GET /health`: shows config without secrets.
- `GET /binance/time`: calls `/fapi/v1/time`.
- `GET /binance/klines?symbol=BTCUSDT&interval=1m&limit=5`: calls `/fapi/v1/klines`.
- `GET /binance/account`: calls signed `/fapi/v2/account`.
- `GET /binance/orders?symbol=BTCUSDT&startTime=...&endTime=...`: calls signed `/fapi/v1/allOrders`.
- `POST /binance/orders/payload`: returns the Binance order params without calling Binance.
- `POST /binance/orders/test`: calls signed `/fapi/v1/order/test`.
- `POST /binance/orders/submit?confirm_live_order=true`: submits a real order through `/fapi/v1/order`.
- `POST /binance/listen-key`: starts a user data stream listen key.
- `PUT /binance/listen-key/{listen_key}`: keepalive for a listen key.
- `DELETE /binance/listen-key/{listen_key}`: closes a listen key.
- `POST /binance/raw`: calls an arbitrary Binance path for manual inspection.

## Order Body Example

Market:

```json
{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "type": "MARKET",
  "quantity": "0.001",
  "newClientOrderId": "manual-test-001"
}
```

Limit:

```json
{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "type": "LIMIT",
  "quantity": "0.001",
  "price": "50000",
  "timeInForce": "GTC",
  "newClientOrderId": "manual-test-002"
}
```

Use `/binance/orders/test` before `/binance/orders/submit`. The submit endpoint rejects requests unless `confirm_live_order=true` is set.

## Raw Body Example

```json
{
  "method": "GET",
  "path": "/fapi/v1/exchangeInfo",
  "params": {},
  "signed": false,
  "api_key_required": false
}
```
