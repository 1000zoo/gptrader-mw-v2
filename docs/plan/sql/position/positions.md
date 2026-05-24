# positions

- Status: `done`
- Domain: position
- Source: `src/domain/position/position.py`, `src/application/usecases/trade/sync_position_usecase.py`

## 목적

현재 포지션 상태를 저장한다. 프로세스 재시작 후 포지션 복구와 주문/체결 이벤트 반영의 기준 상태로 사용한다.

## 저장 단위

한 row는 하나의 현재 포지션 상태다. 상태 변경 이력은 `position_events`에 append-only로 저장한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| position_id | text | yes | 포지션 식별자. |
| symbol | text | yes | 포지션 심볼. |
| direction | text | yes | `long` 또는 `short`. |
| quantity | numeric | yes | 현재 수량. 0 이상. |
| average_entry_price | numeric | yes | 평균 진입가. 0보다 커야 한다. |
| status | text | yes | `open` 또는 `closed`. |
| opened_dt | timestamptz | no | 포지션 개시 시각. |
| closed_dt | timestamptz | no | 포지션 종료 시각. |
| last_event_id | text | no | 마지막 반영 이벤트 id. |
| metadata | json | no | 거래소 포지션 id 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `position_id`
- Index: `(symbol, status, reg_ymd, upd_dt)`
- Check: `direction IN ('long', 'short')`, `status IN ('open', 'closed')`, `quantity >= 0`, `average_entry_price > 0`, `use_yn IN ('Y', 'N')`
