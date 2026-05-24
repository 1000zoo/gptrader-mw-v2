# risk_checks

- Status: `ready`
- Domain: risk
- Source: `src/domain/risk/risk_policy.py`, `src/application/usecases/trade/execute_trade_usecase.py`

## 목적

거래 진입 전 리스크 정책의 허용/차단 결과를 저장한다. 차단 사유와 주문 미발생 원인을 추적한다.

## 저장 단위

한 row는 하나의 `RiskCheck` 결과다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| risk_check_id | text | yes | 리스크 검사 식별자. |
| decision_id | text | no | 검사 대상 `trade_decisions.decision_id`. |
| exposure_limit_id | text | yes | 사용한 `exposure_limits.exposure_limit_id`. |
| requested_notional | numeric | yes | 요청 진입 notional. 0 이상. |
| allowed | boolean | yes | 진입 허용 여부. |
| reason | text | yes | `allowed`, `not_entry_decision`, `total_exposure_exceeded`, `symbol_exposure_exceeded`. |
| metadata | json | no | 정책 버전 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `risk_check_id`
- Index: `(allowed, reason, reg_ymd, reg_dt)`
- Check: `requested_notional >= 0`, reason enum, `use_yn IN ('Y', 'N')`
