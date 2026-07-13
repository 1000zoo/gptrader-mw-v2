# Module N Infrastructure Exchange Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the exchange infrastructure boundary with exchange-specific adapters, mapper functions, and explicit follow-up work for live Binance integration.

**Architecture:** Keep `src/infrastructure/exchange` split by exchange first, then external responsibility: `binance/market_data`, `binance/account`, `binance/order_execution`, and `binance/position_stream`. This pass creates Binance-oriented adapter skeletons that implement domain ports and pure response mappers, while preventing raw vendor payloads from leaking upward. Binance adapters should own their Binance API/client boundary internally rather than requiring callers to inject a raw Binance client on every adapter; callers should pass project-level configuration or a small internal gateway only when test seams or operational settings require it. Responsibility-level packages may re-export concrete adapters, but implementation files stay under the exchange-specific directory so Upbit or another venue can be added beside Binance.

**Tech Stack:** Python dataclasses, domain `Protocol` ports, pytest.

---

### Task 1: Market Data Adapter Boundary

**Files:**
- Create: `tests/infrastructure/exchange/test_binance_market_data_adapter.py`
- Create: `src/infrastructure/exchange/__init__.py`
- Create: `src/infrastructure/exchange/binance/__init__.py`
- Create: `src/infrastructure/exchange/binance/market_data/__init__.py`
- Create: `src/infrastructure/exchange/binance/market_data/binance_market_data_adapter.py`
- Create: `src/infrastructure/exchange/binance/market_data/binance_market_data_mapper.py`

**Steps:**
1. Write a failing test that maps Binance kline payload rows into chronological domain `Candle` objects and `MarketSnapshot`.
2. Run `pytest tests/infrastructure/exchange/test_binance_market_data_adapter.py -q` and verify it fails because the module does not exist.
3. Implement the minimal mapper and injected-client adapter.
4. Re-run the test and verify it passes.

### Task 2: Account Adapter Boundary

**Files:**
- Create: `tests/infrastructure/exchange/test_binance_account_adapter.py`
- Create: `src/infrastructure/exchange/binance/account/__init__.py`
- Create: `src/infrastructure/exchange/binance/account/binance_account_adapter.py`
- Create: `src/infrastructure/exchange/binance/account/binance_account_mapper.py`

**Steps:**
1. Write a failing test that maps Binance account balance payloads into `AccountSnapshot` and `AssetBalance`.
2. Run `pytest tests/infrastructure/exchange/test_binance_account_adapter.py -q` and verify it fails because the module does not exist.
3. Implement the minimal mapper and injected-client adapter.
4. Re-run the test and verify it passes.

### Task 3: Order Execution Adapter Boundary

**Files:**
- Create: `tests/infrastructure/exchange/test_binance_order_execution_adapter.py`
- Create: `src/infrastructure/exchange/binance/order_execution/__init__.py`
- Create: `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py`
- Create: `src/infrastructure/exchange/binance/order_execution/binance_order_execution_mapper.py`

**Steps:**
1. Write a failing test that maps domain `OrderRequest` into Binance order parameters and maps Binance order payloads into `OrderResult`.
2. Run `pytest tests/infrastructure/exchange/test_binance_order_execution_adapter.py -q` and verify it fails because the module does not exist.
3. Implement the minimal mapper and injected-client adapter.
4. Re-run the test and verify it passes.

### Task 4: Position Stream Boundary And Follow-Up Notes

**Files:**
- Create: `src/infrastructure/exchange/binance/position_stream/__init__.py`
- Create: `src/infrastructure/exchange/binance/position_stream/README.md`
- Modify: `docs/progress.md`

**Steps:**
1. Document that live WebSocket stream handling is intentionally deferred to Module T integration.
2. Record follow-up work in `docs/progress.md` so later sessions can see that live Binance clients, authentication, retry policy, and stream runtime remain.
3. Run infrastructure exchange tests and full pytest suite.

### Task 5: Binance Client Ownership Refactor

**Files:**
- Modify: `src/infrastructure/exchange/binance/market_data/binance_market_data_adapter.py`
- Modify: `src/infrastructure/exchange/binance/account/binance_account_adapter.py`
- Modify: `src/infrastructure/exchange/binance/order_execution/binance_order_execution_adapter.py`
- Create: `src/infrastructure/exchange/binance/binance_config.py`
- Create: `src/infrastructure/exchange/binance/binance_client_factory.py`
- Modify: `tests/infrastructure/exchange/test_binance_market_data_adapter.py`
- Modify: `tests/infrastructure/exchange/test_binance_account_adapter.py`
- Modify: `tests/infrastructure/exchange/test_binance_order_execution_adapter.py`

**Intent:**
The current Binance adapters are over-injected: even though they live under `infrastructure/exchange/binance`, callers still have to provide a Binance-shaped client object. That makes the composition root responsible for vendor API details and lets fake method names drift away from the actual Binance futures SDK.

Refactor the boundary so Binance-specific code owns one of these implementation choices internally:

- call Binance REST endpoints directly through a small project-owned gateway,
- use `binance-futures-connector` behind a project-owned factory/wrapper,
- or replace it later with another internal Binance library without changing domain/application callers.

The upper layers should depend only on domain ports plus Binance configuration, not on the concrete vendor client object.

**Step 1: Write failing tests for adapter construction without raw client injection**

Add tests that instantiate each adapter from configuration or an internal gateway factory seam, not from a raw Binance client. The tests should assert that:

- `BinanceMarketDataAdapter` can be constructed without passing a vendor client object.
- `BinanceAccountAdapter` can be constructed without passing a vendor client object.
- `BinanceOrderExecutionAdapter` can be constructed without passing a vendor client object.
- tests patch only the project-owned factory/gateway seam, not arbitrary Binance SDK method names.

**Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/infrastructure/exchange/test_binance_market_data_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py -q
```

Expected: FAIL because adapters currently require `client` injection.

**Step 3: Add Binance configuration and factory/wrapper**

Create a small Binance configuration object for API key, secret, base URL/testnet flag, timeout, and recv window. Create a project-owned factory or gateway that hides the selected Binance access method.

If using `binance-futures-connector`, normalize the SDK method names in this wrapper so adapters call project-owned methods such as:

- `load_klines(symbol, interval, limit)`
- `load_account()`
- `submit_order(**params)`
- `load_orders(symbol, start_time, end_time)`

The wrapper maps those calls to the actual SDK methods, for example `klines`, `account`, `new_order`, and `get_all_orders` if that is the chosen SDK contract.

**Step 4: Refactor adapters to own the Binance boundary**

Update the three Binance adapters so their default constructor builds or receives the project-owned gateway/factory, not a raw vendor client. Keep mapper functions pure and unchanged where possible.

Allowed constructor shapes:

```python
BinanceMarketDataAdapter(config: BinanceConfig, gateway: BinanceGateway | None = None)
BinanceAccountAdapter(config: BinanceConfig, gateway: BinanceGateway | None = None)
BinanceOrderExecutionAdapter(config: BinanceConfig, gateway: BinanceGateway | None = None)
```

The optional gateway is a test seam and internal infrastructure seam. It must not leak raw SDK method names into application or interface modules.

**Step 5: Re-run targeted exchange tests**

Run:

```bash
pytest tests/infrastructure/exchange -q
```

Expected: PASS.

**Step 6: Run full verification**

Run:

```bash
pytest
```

Expected: PASS.

## Deferred Work For Later Agents

This Module N pass intentionally leaves the following work for later sessions:

- Refactor Binance adapters so they own Binance API/client construction behind a project-owned gateway or factory, instead of requiring raw vendor client injection from callers.
- Add retry, timeout, rate-limit, and exchange error translation policy.
- Implement authenticated position/user-data stream runtime with reconnect and heartbeat handling.
- Wire concrete adapters into Module R/S/T composition roots once those interface modules exist.
- Add future exchanges as sibling directories such as `src/infrastructure/exchange/upbit/`, with the same responsibility subpackages.
