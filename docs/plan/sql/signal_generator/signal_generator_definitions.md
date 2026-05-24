# signal_generator_definitions

- Status: `done`
- Domain: signal_generator/lifecycle
- Source: `src/domain/lifecycle/signal_generator_definition.py`, `src/infrastructure/persistence/repositories/sqlite_strategy_repository.py`, `sql/ddl/signal_generator/tables/signal_generator_definitions.sql`

## 목적

시그널 생성기의 구성 이름과 원본 정의 payload를 저장한다. 포함 전략과 레짐 라우팅은 별도 상세 테이블로 정규화할 수 있다.

## 저장 단위

한 row는 하나의 `SignalGeneratorDefinition`이다. 현재 SQLite adapter는 `strategy_ids`, `regime_routes`, `metadata`를 `payload`에 보관한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| generator_id | text | yes | 시그널 생성기 식별자. PK. |
| name | text | yes | 운영 표시명. |
| payload | json/text | yes | `strategy_ids`, `regime_routes`, `metadata`를 포함한 원본 정의 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `generator_id`
- Index: `(reg_ymd, generator_id)`
- Check: `generator_id <> ''`, `name <> ''`, `use_yn IN ('Y', 'N')`
