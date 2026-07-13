# order_requests

- Status: `done`
- Domain: execution
- Source: `src/domain/execution/order_request.py`, `src/application/usecases/trade/execute_trade_usecase.py`, `src/application/usecases/trade/close_position_usecase.py`

## 목적

내부 주문 요청을 저장한다. 어떤 시그널/판단/포지션에서 거래소 주문 요청이 발생했는지 추적한다.

## 저장 단위

한 row는 하나의 `OrderRequest`다. `client_order_id`는 외부 거래소 요청과 내부 추적을 연결하는 핵심 키다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| request_id | text | yes | 내부 주문 요청 식별자. |
| client_order_id | text | yes | 거래소에 전달하는 client order id. |
| decision_id | text | no | 원인이 된 `trade_decisions.decision_id`. |
| position_id | text | no | 청산 주문인 경우 대상 포지션 id. |
| symbol | text | yes | 주문 심볼. |
| side | text | yes | `long` 또는 `short`. |
| order_type | text | yes | `market` 또는 `limit`. |
| quantity | numeric | yes | 주문 수량. 0보다 커야 한다. |
| limit_price | numeric | no | 지정가 주문 가격. 시장가 주문이면 null. |
| reduce_only | boolean | yes | 청산 전용 주문 여부. |
| payload | json | no | 거래소 제출 전 원본/확장 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `request_id`
- Unique: `client_order_id`
- Index: `(symbol, reg_ymd, reg_dt)`
- Index: `(decision_id, reg_ymd, reg_dt)`
- Check: side/order_type enum, quantity/limit price domain rules, `use_yn IN ('Y', 'N')`
