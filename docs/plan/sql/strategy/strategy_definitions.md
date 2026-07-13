# strategy_definitions

- Status: `done`
- Domain: strategy/lifecycle
- Source: `src/domain/lifecycle/strategy_definition.py`, `src/infrastructure/persistence/repositories/sqlite_strategy_repository.py`, `sql/ddl/strategy/tables/strategy_definitions.sql`

## 목적

등록 가능한 개별 전략의 구현 식별자, 버전, 파라미터를 저장한다. 전략 수명주기와 시그널 생성기 구성이 참조하는 기준 테이블이다.

## 저장 단위

한 row는 하나의 `StrategyDefinition`이다. 같은 `strategy_id` 저장은 현재 SQLite adapter에서 upsert된다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| strategy_id | text | yes | 전략 식별자. PK. |
| name | text | yes | 운영 표시명. |
| implementation | text | yes | 전략 구현 경로 또는 구현 키. |
| version | text | yes | 전략 정의 버전. |
| payload | json/text | yes | `parameters`, `metadata`를 포함한 원본 정의 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `strategy_id`
- Index: `(reg_ymd, strategy_id)`
- Check: `strategy_id <> ''`, `name <> ''`, `implementation <> ''`, `version <> ''`, `use_yn IN ('Y', 'N')`
