# Frozen K4 Diagnostic Purge Design

## Goal

Retire the completed frozen-K4 diagnostic implementation and machine-readable evidence while preserving one concise Markdown record. General regime clustering, model fitting, mapping, selection, and strategy runtime remain in place.

## Final retained evidence

Keep exactly one frozen-K4 diagnostic document:

`docs/backtests/frozen-k4-diagnosis-summary.md`

It records only the minimum durable evidence:

- model, period, and sample population;
- reproduced failed metrics and exact OOD accounting;
- Component 0 OOD top-five features and the three fixed concentration decisions;
- 3-day and 7-day offset drift/OOD/top-feature consistency conclusions;
- parent and child run identifiers, relevant artifact/commit provenance, and verification status;
- an explicit statement that diagnosis is complete and strategy Mapping was not resumed.

The summary is written from the already independently verified evidence before any source artifact is removed.

## Deleted slice

Delete both frozen-K4 diagnostic evidence trees, their manifests and tabular/JSON payloads, the frozen-K4 failure/completion/auditor scripts, diagnostic-only domain/application/infrastructure modules, their public exports, all dedicated tests, and the 2026-07-17/18 frozen-K4 design and implementation documents.

The cleanup design and implementation-plan documents are also deleted in the final cleanup commit so they do not violate the one-document result. Their Git history remains available.

## Preserved boundaries

Do not delete or modify general chart-regime/GMM model fitting, artifacts, historical replay, regime mapping, regime selection, scheduler integration, or strategy runtime. Preserve the chart-regime K4 model and mapping evidence because they are inputs or outputs of the general regime system rather than frozen-diagnostic machinery.

Remove frozen-K4 exports from package `__init__` files and confirm no surviving production/test/document reference points at a deleted diagnostic module or evidence path.

## Verification

After deletion:

1. search the repository for frozen-K4 diagnostic module, script, test, plan, and artifact references;
2. require the single summary Markdown to be the only surviving frozen-K4 diagnostic document;
3. run general regime and mapping focused tests;
4. run the full repository test suite;
5. confirm the worktree contains only the intended summary, deletions, and export cleanup before committing.

