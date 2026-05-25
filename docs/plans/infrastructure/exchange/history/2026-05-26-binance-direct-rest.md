# Binance Direct REST Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove raw Binance client injection from exchange adapters and call Binance USD-M Futures REST API through project-owned direct REST boundaries.

**Architecture:** Add `BinanceConfig` and a small direct REST helper for unsigned and signed Binance requests. Keep endpoint-specific API functions inside each adapter script so Binance API input/output changes are isolated to those functions. Tests patch these project-owned API functions instead of fake vendor clients.

**Tech Stack:** Python dataclasses, stdlib `urllib.request`, stdlib `hmac`/`hashlib`, pytest monkeypatch.

---

### Task 1: Add Binance Config And REST Helper

**Files:**
- Create: `src/infrastructure/exchange/binance/binance_config.py`
- Create: `src/infrastructure/exchange/binance/binance_rest.py`
- Test: `tests/infrastructure/exchange/test_binance_rest.py`

**Step 1: Write failing config and signing tests**

Add tests for:

- `BinanceConfig.default()` returns the production USD-M Futures base URL.
- `BinanceConfig.from_env()` reads API key and secret from environment.
- `sign_params` appends a stable HMAC SHA256 signature.

**Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_rest.py -q
```

Expected: FAIL because modules do not exist.

**Step 3: Implement minimal config and REST helper**

Implement:

- `BinanceConfig` dataclass with `api_key`, `api_secret`, `base_url`, `timeout`, `recv_window`.
- `default()` and `from_env()`.
- `sign_params(params, secret)`.
- `request_json(config, method, path, params=None, signed=False)`.

Use stdlib HTTP to avoid Binance SDK dependency.

**Step 4: Run tests to verify pass**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_rest.py -q
```

Expected: PASS.

### Task 2: Refactor Market Data Adapter

**Files:**
- Modify: `src/infrastructure/exchange/binance/market_data/binance_market_data_adapter.py`
- Modify: `tests/infrastructure/exchange/test_binance_market_data_adapter.py`

**Step 1: Update tests first**

Change tests to instantiate:

```python
adapter = BinanceMarketDataAdapter(BinanceConfig.default())
```

Patch `load_klines_api` in the adapter module and assert it receives `config`, `symbol`, `interval`, and `limit`.

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_market_data_adapter.py -q
```

Expected: FAIL because adapter still requires a raw client.

**Step 3: Implement direct API function**

Add:

```python
def load_klines_api(config: BinanceConfig, symbol: str, interval: str, limit: int) -> list[object]:
    return request_json(
        config,
        "GET",
        "/fapi/v1/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
    )
```

Update the adapter to call this function instead of `self._client.get_klines`.

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_market_data_adapter.py -q
```

Expected: PASS.

### Task 3: Refactor Account Adapter

**Files:**
- Modify: `src/infrastructure/exchange/binance/account/binance_account_adapter.py`
- Modify: `tests/infrastructure/exchange/test_binance_account_adapter.py`

**Step 1: Update tests first**

Change tests to instantiate with `BinanceConfig.default()` and patch `load_account_api`.

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_account_adapter.py -q
```

Expected: FAIL because adapter still requires a raw client.

**Step 3: Implement signed account API function**

Add:

```python
def load_account_api(config: BinanceConfig) -> Mapping[str, object]:
    return request_json(config, "GET", "/fapi/v2/account", signed=True)
```

Update the adapter to call this function.

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_account_adapter.py -q
```

Expected: PASS.

### Task 4: Refactor Order Execution Adapter

**Files:**
- Modify: `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py`
- Modify: `tests/infrastructure/exchange/test_binance_order_execution_adapter.py`

**Step 1: Update tests first**

Change tests to instantiate with `BinanceConfig.default()`. Patch:

- `submit_order_api`
- `load_orders_api`

Assert the patched functions receive mapped Binance params and epoch millisecond bounds.

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_order_execution_adapter.py -q
```

Expected: FAIL because adapter still requires a raw client.

**Step 3: Implement signed order API functions**

Add:

```python
def submit_order_api(config: BinanceConfig, params: Mapping[str, object]) -> Mapping[str, object]:
    return request_json(config, "POST", "/fapi/v1/order", params=params, signed=True)

def load_orders_api(
    config: BinanceConfig,
    symbol: str,
    start_time: int,
    end_time: int,
) -> list[Mapping[str, object]]:
    return request_json(
        config,
        "GET",
        "/fapi/v1/allOrders",
        params={"symbol": symbol, "startTime": start_time, "endTime": end_time},
        signed=True,
    )
```

Update adapter methods to call these functions.

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_order_execution_adapter.py -q
```

Expected: PASS.

### Task 5: Verify Exchange Boundary

**Files:**
- Modify as needed: `src/infrastructure/exchange/binance/__init__.py`

**Step 1: Run targeted exchange tests**

Run:

```bash
pytest tests/infrastructure/exchange -q
```

Expected: PASS.

**Step 2: Search for old client injection**

Run:

```bash
rg -n "Binance.*Adapter\\(|client: Any|_client|get_klines|create_order|futures_account|get_account|get_all_orders" src tests
```

Expected: no Binance adapter constructor or implementation depends on raw client injection.

**Step 3: Run full test suite**

Run:

```bash
pytest
```

Expected: PASS.
