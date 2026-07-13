# Module O Infrastructure Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first persistence adapter for lifecycle and signal log repository ports.

**Architecture:** Add a SQLite-backed infrastructure repository layer that serializes domain models to JSON columns and returns domain objects through existing ports. Keep schema helpers, row models, and SQL assets inside infrastructure and `sql`.

**Tech Stack:** Python 3, `sqlite3`, `json`, `pytest`, existing domain port protocols.

---

### Task 1: Progress And Package Skeleton

**Files:**
- Modify: `docs/progress.md`
- Create: `src/infrastructure/persistence/__init__.py`
- Create: `src/infrastructure/persistence/models/__init__.py`
- Create: `src/infrastructure/persistence/repositories/__init__.py`
- Create: `src/infrastructure/persistence/migrations/__init__.py`

**Step 1: Mark Module O in progress**

Change Module O status in `docs/progress.md` from `not started` to `in progress`.

**Step 2: Create package skeleton**

Create the persistence package directories with empty `__init__.py` files.

**Step 3: Verify import skeleton**

Run: `python -m pytest tests/domain/ports/test_strategy_repository_port.py tests/domain/ports/test_signal_log_repository_port.py -q`

Expected: existing tests pass.

### Task 2: Strategy Repository TDD

**Files:**
- Create: `tests/infrastructure/persistence/test_sqlite_strategy_repository.py`
- Create: `src/infrastructure/persistence/repositories/sqlite_strategy_repository.py`
- Create: `src/infrastructure/persistence/models/lifecycle_records.py`

**Step 1: Write failing tests**

Add tests that save and load `StrategyDefinition`, `SignalGeneratorDefinition`, and `StrategyEvaluation` through `SqliteStrategyRepository`.

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/infrastructure/persistence/test_sqlite_strategy_repository.py -q`

Expected: fail because `SqliteStrategyRepository` does not exist.

**Step 3: Implement minimal repository**

Implement schema creation, JSON serialization, upsert for definitions, insert for evaluations, and row deserialization.

**Step 4: Run tests to verify pass**

Run: `python -m pytest tests/infrastructure/persistence/test_sqlite_strategy_repository.py -q`

Expected: pass.

### Task 3: Signal Log Repository TDD

**Files:**
- Create: `tests/infrastructure/persistence/test_sqlite_signal_log_repository.py`
- Create: `src/infrastructure/persistence/repositories/sqlite_signal_log_repository.py`
- Create: `src/infrastructure/persistence/models/signal_log_records.py`

**Step 1: Write failing tests**

Add tests that append and list `SignalLogEntry` objects with nested `GeneratedSignal` data.

**Step 2: Run tests to verify failure**

Run: `python -m pytest tests/infrastructure/persistence/test_sqlite_signal_log_repository.py -q`

Expected: fail because `SqliteSignalLogRepository` does not exist.

**Step 3: Implement minimal repository**

Implement schema creation, JSON serialization for signals/reasons/strategy results, and filtered list queries.

**Step 4: Run tests to verify pass**

Run: `python -m pytest tests/infrastructure/persistence/test_sqlite_signal_log_repository.py -q`

Expected: pass.

### Task 4: SQL Assets

**Files:**
- Create: `sql/ddl/strategy/tables/strategy_definitions.sql`
- Create: `sql/ddl/signal_generator/tables/signal_generator_definitions.sql`
- Create: `sql/ddl/lifecycle/tables/strategy_evaluations.sql`
- Create: `sql/ddl/signal/tables/signal_logs.sql`
- Create: `sql/ddl/<domain>/indexes/<table_name>_indexes.sql`
- Create: `sql/ddl/<domain>/constraints/<table_name>_constraints.sql`
- Create: `sql/tests/persistence_schema_checks.sql`
- Create: `sql/plans/2026-05-24-module-o-persistence.sql.md`
- Create: `sql/seeds/persistence_seed.sql`

**Step 1: Add DDL and SQL checklist assets**

Add table DDL with common columns, `use_yn` checks, PKs, and indexes that include `reg_ymd` where useful.

**Step 2: Verify SQL assets are present**

Run: `find sql -maxdepth 3 -type f | sort`

Expected: new SQL files are listed.

### Task 5: Final Verification And Progress

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `python -m pytest tests/infrastructure/persistence tests/domain/ports -q`

Expected: pass.

**Step 2: Run full test suite**

Run: `python -m pytest -q`

Expected: pass.

**Step 3: Mark Module O done**

Update Module O status to `done` and add a `2026-05-24 Module O` work log with plan and design document paths.
