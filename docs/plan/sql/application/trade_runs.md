# trade_runs

- Status: `ready`
- Domain: application
- Source: `src/application/usecases/trade/execute_trade_usecase.py`, `src/application/usecases/trade/dto.py`

## 목적

`ExecuteTradeUseCase` 한 번의 실행 결과를 저장한다. 시장 입력, 지표 입력, 생성 시그널, 리스크 결과, 주문 결과를 하나의 감사 단위로 묶는다.

## 저장 단위

한 row는 하나의 실거래 또는 드라이런성 거래 실행 시도다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| trade_run_id | text | yes | 거래 실행 식별자. |
| symbol | text | yes | 실행 심볼. |
| timeframe | text | yes | 실행 타임프레임. |
| candle_limit | integer | yes | 요청 캔들 개수. |
| snapshot_id | text | no | 사용한 `market_snapshots.snapshot_id`. |
| indicator_set_id | text | no | 사용한 `indicator_sets.indicator_set_id`. |
| signal_id | text | yes | command의 signal id 또는 최종 signal id. |
| generator_id | text | yes | 실행 generator id. |
| generated_signal_id | text | no | 저장된 `generated_signals.generated_signal_id`. |
| exposure_limit_id | text | no | 사용한 `exposure_limits.exposure_limit_id`. |
| risk_check_id | text | no | `risk_checks.risk_check_id`. |
| order_id | text | no | 주문 결과 id. |
| status | text | yes | `order_submitted`, `skipped`, `risk_rejected`. |
| reason | text | no | skip 또는 reject 사유. |
| payload | json | no | command/result 원본 payload. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `trade_run_id`
- Index: `(symbol, timeframe, reg_ymd, reg_dt)`
- Index: `(generator_id, status, reg_ymd, reg_dt)`
- Check: status enum, `candle_limit > 0`, `use_yn IN ('Y', 'N')`
