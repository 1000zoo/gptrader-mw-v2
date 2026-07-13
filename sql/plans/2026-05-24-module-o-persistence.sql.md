# Module O Persistence SQL Plan

## Scope

The first persistence schema covers lifecycle definitions, strategy evaluations, and generated signal logs.

## Tables

- `strategy_definitions`
- `signal_generator_definitions`
- `strategy_evaluations`
- `signal_logs`

## Checklist

- Each table includes `reg_ymd`, `reg_dt`, `upd_dt`, and `use_yn`.
- Each table constrains `use_yn` to `Y` or `N`.
- Primary keys are defined in table DDL.
- Indexes include `reg_ymd` where useful for retention and date-scoped queries.
- Application and domain layers do not import DB driver types.

## Migration Notes

The SQLite adapter creates this schema on initialization for local tests and early development. A production PostgreSQL migration can reuse the table and index names while replacing `TEXT` JSON payloads with `JSONB` if needed.
