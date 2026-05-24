# SQL DDL Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a canonical `./sql` structure and agent rules for table-level DDL management.

**Architecture:** Keep canonical SQL schema assets outside Python source under `./sql`. Persistence code remains under `src/infrastructure/persistence`, while table DDL, index DDL, constraints, SQL tests, and SQL planning notes live under `./sql`.

**Tech Stack:** Markdown documentation, PostgreSQL-compatible SQL conventions.

---

### Task 1: Add Project-Level SQL DDL Rules

**Files:**
- Modify: `docs/codex.md`

**Step 1: Add DDL ownership rules**

Add a section that defines `./sql` as the source of truth for table DDL, index DDL, constraints, SQL tests, and SQL planning notes.

**Step 2: Add mandatory table checklist**

Require every table DDL to include `reg_ymd`, `reg_dt`, `upd_dt`, and `use_yn`; require `use_yn` to allow only `Y` and `N`.

**Step 3: Verify**

Run: `rg -n "SQL|DDL|reg_ymd|use_yn" docs/codex.md`

Expected: The new DDL section and checklist are visible.

### Task 2: Update Module O Persistence Plan

**Files:**
- Modify: `docs/plan/modules/module-o-infrastructure-persistence.md`
- Modify: `docs/plan/plan.md`

**Step 1: Clarify split of responsibilities**

State that `src/infrastructure/persistence` owns repository implementations, persistence models, and migration application logic, while `./sql` owns canonical schema DDL.

**Step 2: Add `./sql` to included outputs**

Add `./sql/ddl/<domain>/tables`, `./sql/ddl/<domain>/indexes`, `./sql/ddl/<domain>/constraints`, `./sql/tests`, and `./sql/plans` to Module O outputs.

**Step 3: Verify**

Run: `rg -n "./sql|DDL|persistence" docs/plan/plan.md docs/plan/modules/module-o-infrastructure-persistence.md`

Expected: Both the global plan and Module O reference the SQL DDL structure.

### Task 3: Create SQL Directory Skeleton

**Files:**
- Create: `sql/README.md`
- Create: `sql/ddl/README.md`
- Create: `sql/ddl/<domain>/tables/`
- Create: `sql/ddl/<domain>/indexes/`
- Create: `sql/ddl/<domain>/constraints/`
- Create: `sql/tests/README.md`
- Create: `sql/plans/README.md`
- Create: `sql/seeds/README.md`

**Step 1: Add directory documentation**

Document naming, ownership, and checklist rules in `sql/README.md`.

**Step 2: Add subdirectory guidance**

Each subdirectory README should explain what belongs there and how agents should update it.

**Step 3: Verify**

Run: `find sql -maxdepth 3 -type f | sort`

Expected: The README files are present under each SQL category.
