# Planning Documents

`docs/plans` mirrors the top-level `src` architecture. When changing a feature, read the matching `latest.md` first, then inspect `history/` only when the latest document points to a detail you need.

## Structure

- `domain/<module>/latest.md`: domain model and policy planning.
- `application/<usecase>/latest.md`: use case planning.
- `infrastructure/<adapter>/latest.md`: external system and persistence planning.
- `interfaces/<entrypoint>/latest.md`: API, scheduler, websocket, CLI entry point planning.
- `operations/<topic>/latest.md`: cross-cutting runtime, deployment, and live-operation planning.
- `documentation/<topic>/latest.md`: planning and documentation process changes.

Each `latest.md` must include:

- the source path it governs,
- the current plan status,
- the current architectural decision,
- a short change history with links to historical plan files,
- follow-up work that affects future agents.

Historical plan files stay under `history/` and must not be deleted when the plan changes.
