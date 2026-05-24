# position_sizes

- Status: `done`
- Domain: risk
- Source: `src/domain/risk/position_sizer.py`, `src/application/usecases/trade/execute_trade_usecase.py`

## 목적

포지션 사이징 계산 결과를 저장한다. 시그널 신뢰도, 노출 한도, 설정값이 최종 주문 수량으로 이어진 과정을 감사한다.

## 저장 단위

한 row는 하나의 `PositionSize` 계산 결과다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| position_size_id | text | yes | 포지션 사이징 결과 식별자. |
| decision_id | text | no | 사이징 대상 `trade_decisions.decision_id`. |
| exposure_limit_id | text | yes | 사용한 `exposure_limits.exposure_limit_id`. |
| config_id | text | no | 사용한 `position_sizer_configs.config_id`. |
| entry_price | numeric | yes | 진입 기준 가격. 0보다 커야 한다. |
| notional | numeric | yes | 계산된 주문 notional. 0 이상. |
| quantity | numeric | yes | 계산된 주문 수량. 0 이상. |
| metadata | json | no | 계산 입력 또는 보정 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `position_size_id`
- Index: `(decision_id, reg_ymd, reg_dt)`
- Check: `entry_price > 0`, `notional >= 0`, `quantity >= 0`, `use_yn IN ('Y', 'N')`
