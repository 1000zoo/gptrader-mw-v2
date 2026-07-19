# Frozen K4 Diagnostic Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the frozen-K4 diagnostic implementation and machine-readable evidence with one concise Markdown evidence record while preserving the general regime/GMM runtime.

**Architecture:** Extract the already verified conclusions into a stable summary before deleting their source artifacts. Then remove the isolated frozen-K4 diagnostic modules, scripts, tests, exports, evidence trees, and historical design documents; finish with repository-wide reference scans and regression tests proving the general regime system still works.

**Tech Stack:** Markdown, Python 3.14, pytest, Git, PowerShell/`rg` repository checks.

---

### Task 1: Create the single durable evidence record

**Files:**
- Create: `docs/backtests/frozen-k4-diagnosis-summary.md`

- [ ] **Step 1: Record the source evidence before deletion**

Read the committed parent and completion reports and record these exact verified values:

```text
parent_run_id=d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af
parent_manifest_sha256=5b65aed30c9a8d7c67cf383df9667d599c9fb2938b95b59813be5235077a0824
completion_run_id=eac28399d7cc4e2ab40823560b451af65b4a72fb46166a12406bd7b0bc1da0c5
completion_manifest_sha256=5229ecbf5426abac36aaed07d359691abc7096d5bf9151d47e0211e5976ab24d
sample_count=1641
half_A=820
half_B=821
fitted_parameter_centroid_distance=2.3526219570607076
ood=76/1641
ood_rate=0.04631322364411944
component_0_ood=24/409
```

- [ ] **Step 2: Write the concise Markdown**

The document must contain only these sections:

```markdown
# Frozen K4 diagnosis — retained evidence

## Scope and provenance
## Reproduced failure
## Component 0 OOD cause
## Offset stability
## Boundary
```

Record the Component 0 top five as `volume_cv_3d`, `rv_ratio_1d_3d`, `volume_ratio_1d_3d`, `directional_efficiency_3d`, and `max_runup_3d`. Record the maximum single-feature ratio `0.06744504448284344`, strict volatility-family ratio `0.18227287037132553`, and maximum top-1 recurrence ratio `0.125`; therefore all three fixed concentration flags are false. State that strict volatility includes only `rv_4h`, `rv_1d`, `rv_3d`, and `rv_ratio_1d_3d`, excluding range and volume.

Record offset conclusions exactly:

```text
maximum drift component 3: 3/3 three-day, 7/7 seven-day
maximum OOD component 0: 2/3 three-day, 1/7 seven-day
ordered full-sample top-five match: 0/3 three-day, 0/7 seven-day
top-five set match: 2/3 three-day, 0/7 seven-day
```

State that the cause diagnosis is complete, no gate was re-evaluated, and no strategy Mapping was performed.

- [ ] **Step 3: Validate the summary against current evidence**

Run:

```powershell
rg -n "2\.3526219570607076|76/1641|24/409|volume_cv_3d|0\.18227287037132553|3/3|7/7|no strategy Mapping" docs/backtests/frozen-k4-diagnosis-summary.md
```

Expected: every required evidence class has at least one match.

- [ ] **Step 4: Commit the retained evidence**

```powershell
git add docs/backtests/frozen-k4-diagnosis-summary.md
git commit -m "docs: retain minimal frozen K4 evidence"
```

### Task 2: Remove frozen-K4 diagnostic implementation and tests

**Files:**
- Delete: `scripts/diagnose_frozen_three_day_k4_failure.py`
- Delete: `scripts/complete_frozen_three_day_k4_diagnosis.py`
- Delete: `scripts/audit_frozen_k4_diagnosis_completion.py`
- Delete: `src/domain/regime/frozen_k4_failure_diagnostics.py`
- Delete: `src/domain/regime/frozen_k4_diagnosis_completion.py`
- Delete: `src/application/services/frozen_k4_failure_replay.py`
- Delete: `src/application/services/frozen_k4_failure_decomposition.py`
- Delete: `src/application/services/frozen_k4_diagnosis_completion.py`
- Delete: `src/infrastructure/regime/frozen_k4_diagnostic_source.py`
- Modify: `src/infrastructure/regime/__init__.py`
- Delete: `tests/test_diagnose_frozen_three_day_k4_failure.py`
- Delete: `tests/test_complete_frozen_three_day_k4_diagnosis.py`
- Delete: `tests/test_audit_frozen_k4_diagnosis_completion.py`
- Delete: `tests/domain/regime/test_frozen_k4_failure_diagnostics.py`
- Delete: `tests/domain/regime/test_frozen_k4_diagnosis_completion.py`
- Delete: `tests/application/services/test_frozen_k4_failure_replay.py`
- Delete: `tests/application/services/test_frozen_k4_failure_decomposition.py`
- Delete: `tests/application/services/test_frozen_k4_diagnosis_completion.py`
- Delete: `tests/infrastructure/regime/test_frozen_k4_diagnostic_source.py`

- [ ] **Step 1: Capture the pre-removal reference boundary**

Run:

```powershell
rg -l "FrozenK4|frozen_k4|load_frozen_k4" src scripts tests
```

Expected: results are limited to the files listed above plus `src/infrastructure/regime/__init__.py`.

- [ ] **Step 2: Remove the diagnostic-only implementation and tests**

Delete every file listed as `Delete` in this task. Do not alter general files such as `src/infrastructure/regime/sklearn_cluster_core.py`, `src/infrastructure/regime/three_day_k4_model_artifact.py`, regime mapping/selection use cases, or their tests.

- [ ] **Step 3: Remove the public source-loader export**

Delete only these import/export entries from `src/infrastructure/regime/__init__.py`:

```python
from src.infrastructure.regime.frozen_k4_diagnostic_source import (
    FrozenK4DiagnosticSource,
    load_frozen_k4_diagnostic_source,
)
```

and:

```python
"FrozenK4DiagnosticSource",
"load_frozen_k4_diagnostic_source",
```

- [ ] **Step 4: Verify no production or test reference survives**

Run:

```powershell
$matches = rg -n "FrozenK4|frozen_k4|load_frozen_k4|frozen_three_day_k4" src scripts tests
if ($LASTEXITCODE -eq 0) { $matches; throw "frozen K4 diagnostic references remain" }
if ($LASTEXITCODE -ne 1) { throw "rg failed" }
```

Expected: success with no matches.

- [ ] **Step 5: Run general regime focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/domain/regime tests/infrastructure/regime tests/application/usecases/regime tests/application/services/test_regime_balance_diagnostics.py tests/application/services/test_regime_historical_replay.py -q
```

Expected: all collected general regime tests pass; no import error references a deleted frozen-K4 module.

- [ ] **Step 6: Commit implementation removal**

```powershell
git add -u scripts src tests
git commit -m "refactor: remove frozen K4 diagnostic machinery"
```

### Task 3: Remove machine evidence and diagnostic process documents

**Files:**
- Delete tree: `docs/backtests/frozen_k4_failure_diagnosis/`
- Delete tree: `docs/backtests/frozen_k4_diagnosis_completion/`
- Delete: `docs/superpowers/specs/2026-07-17-frozen-k4-failure-diagnosis-design.md`
- Delete: `docs/superpowers/plans/2026-07-17-frozen-k4-failure-diagnosis.md`
- Delete: `docs/superpowers/specs/2026-07-18-frozen-k4-diagnosis-completion-design.md`
- Delete: `docs/superpowers/plans/2026-07-18-frozen-k4-diagnosis-completion.md`
- Delete: `docs/superpowers/specs/2026-07-19-frozen-k4-diagnostic-purge-design.md`
- Delete: `docs/superpowers/plans/2026-07-19-frozen-k4-diagnostic-purge.md`

- [ ] **Step 1: Delete both immutable evidence trees as complete units**

Remove the two listed trees only after Task 1 has committed the retained summary. Do not remove `docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json` or any general chart-regime evidence.

- [ ] **Step 2: Delete all frozen-K4 diagnostic process documents**

Remove the six listed design/plan files, including this cleanup design and plan. Their history remains available through Git.

- [ ] **Step 3: Prove the one-document result**

Run:

```powershell
$files = @(rg --files docs | rg "frozen[_-]k4")
if ($files.Count -ne 1) { $files; throw "expected exactly one frozen-K4 document" }
if ($files[0] -notmatch "docs[\\/]backtests[\\/]frozen-k4-diagnosis-summary\.md$") { throw "unexpected retained file" }
```

Expected: the summary Markdown is the only match.

- [ ] **Step 4: Check surviving documentation references**

Run:

```powershell
$matches = rg -n "frozen_k4_failure_diagnosis|frozen_k4_diagnosis_completion|diagnose_frozen_three_day_k4_failure|complete_frozen_three_day_k4_diagnosis|audit_frozen_k4_diagnosis_completion" docs
if ($LASTEXITCODE -eq 0) { $matches; throw "deleted diagnostic references remain" }
if ($LASTEXITCODE -ne 1) { throw "rg failed" }
```

Expected: success with no stale path or command reference.

### Task 4: Final regression verification and cleanup commit

**Files:**
- Verify: `docs/backtests/frozen-k4-diagnosis-summary.md`
- Verify: all remaining repository files

- [ ] **Step 1: Run the full repository test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all remaining tests pass with zero failures.

- [ ] **Step 2: Validate repository state**

Run:

```powershell
git diff --check
git status --short
git diff --stat HEAD
```

Expected: no whitespace errors; status contains only the Task 3 deletions if Tasks 1 and 2 were committed separately.

- [ ] **Step 3: Commit the final purge**

```powershell
git add -u docs
git commit -m "docs: purge frozen K4 diagnostic artifacts"
```

- [ ] **Step 4: Verify the committed result**

Run:

```powershell
git status --short
git log -3 --oneline
```

Expected: clean worktree and three cleanup commits ending with `docs: purge frozen K4 diagnostic artifacts`.

