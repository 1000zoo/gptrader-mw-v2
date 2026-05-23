# Module N Infrastructure Exchange Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the exchange infrastructure boundary with exchange-specific adapters, mapper functions, and explicit follow-up work for live Binance integration.

**Architecture:** Keep `src/infrastructure/exchange` split by exchange first, then external responsibility: `binance/market_data`, `binance/account`, `binance/order_execution`, and `binance/position_stream`. This pass creates Binance-oriented adapter skeletons that implement domain ports through injected clients and pure response mappers, while preventing raw vendor payloads from leaking upward. Responsibility-level packages may re-export concrete adapters, but implementation files stay under the exchange-specific directory so Upbit or another venue can be added beside Binance.

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

## Deferred Work For Later Agents

This Module N pass intentionally leaves the following work for later sessions:

- Add real Binance REST/futures client construction from configuration and credentials.
- Add retry, timeout, rate-limit, and exchange error translation policy.
- Implement `load_execution_reports` against the chosen Binance endpoint.
- Implement authenticated position/user-data stream runtime with reconnect and heartbeat handling.
- Wire concrete adapters into Module R/S/T composition roots once those interface modules exist.
- Add future exchanges as sibling directories such as `src/infrastructure/exchange/upbit/`, with the same responsibility subpackages.
