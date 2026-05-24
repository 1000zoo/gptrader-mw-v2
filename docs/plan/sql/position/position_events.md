# position_events

- Status: `ready`
- Domain: position
- Source: `src/domain/position/position_event.py`, `src/domain/execution/execution_report.py`

## 목적

포지션 상태 전이를 일으킨 이벤트를 append-only로 저장한다. 체결 이벤트 재생, 감사, 상태 복구에 사용한다.

## 저장 단위

한 row는 하나의 `PositionEvent`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| event_id | text | yes | 포지션 이벤트 식별자. |
| position_id | text | yes | 대상 `positions.position_id`. |
| execution_report_id | text | no | 원인이 된 `execution_reports.report_id`. |
| symbol | text | yes | 조회 최적화를 위한 심볼. |
| event_type | text | yes | `increase`, `decrease`, `close`. |
| direction | text | no | 증가 이벤트의 방향. `long` 또는 `short`. |
| quantity | numeric | yes | 이벤트 수량. 0보다 커야 한다. |
| price | numeric | no | 이벤트 가격. 있으면 0보다 커야 한다. |
| occurred_dt | timestamptz | yes | 이벤트 발생 시각. |
| payload | json | no | 외부 이벤트 원본 또는 보강 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `event_id`
- FK 후보: `position_id -> positions.position_id`
- Index: `(position_id, reg_ymd, occurred_dt)`
- Index: `(symbol, event_type, reg_ymd, occurred_dt)`
- Check: enum 값과 numeric 도메인 불변조건, `use_yn IN ('Y', 'N')`
