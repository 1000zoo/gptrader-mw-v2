# order_results

- Status: `ready`
- Domain: execution
- Source: `src/domain/execution/order_result.py`, `src/domain/execution/execution_report.py`

## 목적

거래소 주문 응답을 내부 주문 요청과 연결해 저장한다. 주문 접수, 거절, 체결, 취소 상태를 추적한다.

## 저장 단위

한 row는 하나의 `OrderResult`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| order_id | text | yes | 내부 주문 결과 식별자. |
| request_id | text | no | `order_requests.request_id`. |
| client_order_id | text | yes | 요청과 일치해야 하는 client order id. |
| exchange_order_id | text | no | 거래소 주문 id. |
| status | text | yes | `accepted`, `rejected`, `filled`, `partially_filled`, `canceled`. |
| executed_quantity | numeric | no | 체결 수량. filled/partially_filled에서 필수. |
| average_price | numeric | no | 평균 체결가. filled/partially_filled에서 필수. |
| failure_reason | text | no | rejected 상태 사유. rejected에서 필수. |
| payload | json | no | 거래소 응답 원본. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `order_id`
- FK 후보: `request_id -> order_requests.request_id`
- Index: `(client_order_id, reg_ymd, reg_dt)`
- Index: `(exchange_order_id, reg_ymd, reg_dt)`
- Check: status별 필수 필드 규칙, `use_yn IN ('Y', 'N')`
