# Scheduler Ops Module Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add scheduler persistence layers in `ops` with DB schema, VO, repository, and service using existing project patterns.

**Architecture:** Introduce a new `scheduler` table and mirror existing `ops` module layering (`vo -> repository -> service`). Keep methods minimal (`create/find/find_by_name`) and use existing common DB utilities.

**Tech Stack:** Python, Pydantic VO models, SQLAlchemy text queries, PostgreSQL SQL schema files, pytest.

---

### Task 1: Add failing tests for schema and VO

**Files:**
- Modify: `tests/test_sql_schemas.py`
- Modify: `tests/test_new_vo_models.py`

1. Write tests that assert `sql/012_create_scheduler.sql` exists and contains `CREATE TABLE IF NOT EXISTS scheduler` and `UNIQUE (name)`.
2. Write tests that assert `sql/init.sql` contains scheduler table definition.
3. Write test that imports `DefaultSchedulerVo` and verifies core fields round-trip.
4. Run only these tests and confirm failure.

### Task 2: Add scheduler SQL schemas

**Files:**
- Create: `sql/012_create_scheduler.sql`
- Modify: `sql/init.sql`

1. Add idempotent scheduler create script with required columns and base VO columns (`attr1~attr10`, `reg_dt`, `upd_dt`).
2. Add unique constraint/index for `name`.
3. Add scheduler table section in `sql/init.sql` near other ops tables.

### Task 3: Add VO/Repository/Service in ops module

**Files:**
- Create: `src/ops/vo/scheduler/__init__.py`
- Create: `src/ops/vo/scheduler/default.py`
- Create: `src/ops/vo/scheduler/filter.py`
- Create: `src/ops/repository/scheduler/__init__.py`
- Create: `src/ops/repository/scheduler/scheduler_repo.py`
- Create: `src/ops/service/scheduler/__init__.py`
- Create: `src/ops/service/scheduler/scheduler_service.py`
- Modify: `src/common/db/util.py`

1. Implement VO models with requested columns and base VO fields inherited from `Vo`.
2. Implement repository methods: insert/select/select_by_name.
3. Implement service methods with repository error wrapping.
4. Add `scheduler` to allowed DB tables.

### Task 4: Verify tests

**Files:**
- No new files

1. Run target tests for schemas and VOs.
2. If they pass, run a broader quick subset if needed.
3. Report verification evidence.
