# strategy_evaluations

- Status: `done`
- Domain: lifecycle
- Source: `src/domain/lifecycle/strategy_evaluation.py`, `src/infrastructure/persistence/repositories/sqlite_strategy_repository.py`, `sql/ddl/lifecycle/tables/strategy_evaluations.sql`

## 목적

전략 또는 시그널 생성기 대상의 백테스트/드라이런/승격 평가 결과를 저장한다.

## 저장 단위

한 row는 하나의 `StrategyEvaluation`이다. 현재 SQLite adapter는 `metrics`, `metadata`를 `payload`에 보관한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| evaluation_id | text | yes | 평가 식별자. PK. |
| target_id | text | yes | 평가 대상 전략 또는 generator id. |
| status | text | yes | `draft`, `backtested`, `dry_run`, `promoted`, `archived`. |
| payload | json/text | yes | metrics, metadata를 포함한 평가 원본 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `evaluation_id`
- Index: `(target_id, reg_ymd, reg_dt)`
- Check: `status IN ('draft', 'backtested', 'dry_run', 'promoted', 'archived')`, `use_yn IN ('Y', 'N')`
