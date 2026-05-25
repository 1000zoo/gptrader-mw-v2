# Module A Market Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define the shared market input language for symbols, timeframes, candles, and market snapshots.

**Architecture:** Add pure domain value objects under `src/domain/market` with no exchange, database, or indicator dependencies. Keep validation in object constructors so downstream modules receive stable, vendor-neutral market data.

**Tech Stack:** Python dataclasses, standard library `datetime`, `decimal`, and pytest.

---

### Task 1: Symbol

**Files:**
- Create: `src/domain/market/symbol.py`
- Create: `src/domain/market/__init__.py`
- Test: `tests/domain/market/test_symbol.py`

**Steps:**
1. Write tests for uppercase normalization, required base/quote assets, and stable pair formatting.
2. Run the symbol tests and verify they fail because `Symbol` does not exist.
3. Implement a frozen `Symbol` dataclass with `base_asset`, `quote_asset`, and `pair`.
4. Run the symbol tests and verify they pass.

### Task 2: Timeframe

**Files:**
- Create: `src/domain/market/timeframe.py`
- Test: `tests/domain/market/test_timeframe.py`

**Steps:**
1. Write tests for allowed units, positive duration, canonical labels, and duration seconds.
2. Run the timeframe tests and verify they fail because `Timeframe` does not exist.
3. Implement a frozen `Timeframe` dataclass.
4. Run the timeframe tests and verify they pass.

### Task 3: Candle

**Files:**
- Create: `src/domain/market/candle.py`
- Test: `tests/domain/market/test_candle.py`

**Steps:**
1. Write tests for OHLCV field validation and candle interval consistency.
2. Run the candle tests and verify they fail because `Candle` does not exist.
3. Implement a frozen `Candle` dataclass using `Symbol` and `Timeframe`.
4. Run the candle tests and verify they pass.

### Task 4: Market Snapshot

**Files:**
- Create: `src/domain/market/market_snapshot.py`
- Test: `tests/domain/market/test_market_snapshot.py`

**Steps:**
1. Write tests for non-empty candle collections, consistent symbol/timeframe, and chronological ordering.
2. Run the snapshot tests and verify they fail because `MarketSnapshot` does not exist.
3. Implement a frozen `MarketSnapshot` dataclass.
4. Run all market domain tests and verify they pass.

### Task 5: Progress

**Files:**
- Modify: `docs/progress.md`

**Steps:**
1. Mark Module A as `done`.
2. Add a 2026-05-12 Module A work log with summary and follow-up.
3. Run the final test command again before completion.
