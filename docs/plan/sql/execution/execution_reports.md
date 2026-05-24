# execution_reports

- Status: `ready`
- Domain: execution
- Source: `src/domain/execution/execution_report.py`, `src/domain/ports/order_execution_port.py`, `src/application/usecases/trade/sync_position_usecase.py`

## 목적

주문 요청과 결과를 묶은 체결 리포트를 저장한다. 포지션 이벤트 생성과 동기화의 입력이다.

## 저장 단위

한 row는 하나의 `ExecutionReport`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| report_id | text | yes | 체결 리포트 식별자. |
| request_id | text | yes | `order_requests.request_id`. |
| order_id | text | yes | `order_results.order_id`. |
| position_id | text | no | 반영 대상 포지션 id. |
| symbol | text | yes | 조회 대상 심볼. |
| client_order_id | text | yes | 요청/결과 공통 client order id. |
| exchange_order_id | text | no | 거래소 주문 id. |
| status | text | yes | 주문 결과 상태 중복 저장. |
| executed_quantity | numeric | no | 체결 수량. |
| average_price | numeric | no | 평균 체결가. |
| reduce_only | boolean | yes | 포지션 감소 이벤트 여부 판단용. |
| executed_dt | timestamptz | yes | 체결 또는 리포트 발생 시각. |
| payload | json | no | 거래소 체결 원본 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `report_id`
- FK 후보: `request_id -> order_requests.request_id`, `order_id -> order_results.order_id`
- Index: `(symbol, reg_ymd, executed_dt)`
- Index: `(position_id, reg_ymd, executed_dt)`
- Check: `status` enum, `use_yn IN ('Y', 'N')`
