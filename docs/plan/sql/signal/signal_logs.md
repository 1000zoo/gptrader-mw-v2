# signal_logs

- Status: `done`
- Domain: signal
- Source: `src/domain/ports/signal_log_repository_port.py`, `src/infrastructure/persistence/repositories/sqlite_signal_log_repository.py`, `sql/ddl/signal/tables/signal_logs.sql`

## 목적

시그널 생성기 실행 결과를 append-only 로그로 저장한다. 현재 구현은 `GeneratedSignal` 전체를 payload로 보관한다.

## 저장 단위

한 row는 하나의 `SignalLogEntry`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| signal_id | text | yes | 로그 식별자이자 command에서 전달된 signal id. 현재 DDL의 PK. |
| generator_id | text | yes | 시그널 생성기 id. |
| payload | json/text | yes | `generated_signal` 전체 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `signal_id`
- Index: `(generator_id, reg_ymd, reg_dt)`
- Check: `signal_id <> ''`, `generator_id <> ''`, `use_yn IN ('Y', 'N')`

## 정규화 후속

`signals`, `generated_signals`, `strategy_results`, `signal_reasons`가 구현되면 payload의 주요 조회 필드는 해당 테이블로 승격한다.
