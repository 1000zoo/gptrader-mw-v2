# Planning Documentation Latest Plan

- Source path: `docs/plans`, `docs/codex.md`, `docs/plan/modules/README.md`
- Status: `done` for src-aligned planning document reorganization.
- Governs: how implementation plans are organized, read, and updated by agents.

## Current Plan

`docs/plans` mirrors the top-level `src` architecture. Agents should start from the matching `latest.md` for the feature they are changing, not from date-prefixed files in a flat directory.

Each `latest.md` is the current planning surface and must include enough context for an agent to understand:

- the source path it governs,
- current status,
- current architectural decision,
- relevant history links,
- follow-up work.

Historical plan files are preserved under `history/` and should not be deleted when a plan changes.

## History

- 2026-05-26: Reorganized flat `docs/plans/YYYY-MM-DD-...` files into `docs/plans/<layer>/<module>/history/` and added `latest.md` files for active modules and not-started interface/infrastructure modules.

## Follow-Up

When a feature plan changes, update the corresponding `latest.md` first. If a detailed dated plan is still useful, place it in that module's `history/` directory and link it from `latest.md`.

