# Module O Persistence Design

## Decision

Module O will start with a small SQLite-backed persistence adapter that implements the existing domain repository ports without adding database concerns to `domain` or `application`.

The implementation will use Python's standard `sqlite3` module and JSON payload columns. This keeps the adapter easy to test locally while preserving the port boundary for a later PostgreSQL or SQLAlchemy adapter.

## Scope

- Implement `StrategyRepositoryPort` for strategy definitions, signal generator definitions, and strategy evaluations.
- Implement `SignalLogRepositoryPort` for generated signal logs.
- Add serializer functions that translate between domain dataclasses and JSON-compatible dictionaries.
- Add SQL asset files under `sql/ddl`, `sql/tests`, `sql/plans`, and `sql/seeds` for the first persistence table set.
- Keep schema initialization in infrastructure only.

## Tables

- `strategy_definitions`
- `signal_generator_definitions`
- `strategy_evaluations`
- `signal_logs`

Each table includes `reg_ymd`, `reg_dt`, `upd_dt`, and `use_yn`. `use_yn` is constrained to `Y` or `N`.

## Data Flow

Application use cases call domain ports. The infrastructure repository receives domain objects, serializes nested mappings, enums, and `Decimal` values into JSON text, then writes rows to SQLite. Read paths deserialize rows back into domain objects before returning through the same port interfaces.

## Error Handling

The first adapter does not introduce custom infrastructure exception types. SQLite errors stay inside infrastructure tests for now; application code only sees the existing repository port behavior.

## Testing

Tests will use temporary SQLite database files. They will verify that saved domain objects round-trip through the repository ports, evaluations are filtered by `target_id`, signal logs are filtered by `generator_id`, and schema helper creation does not require application-layer database knowledge.
