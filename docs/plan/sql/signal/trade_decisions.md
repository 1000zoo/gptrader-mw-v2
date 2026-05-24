# trade_decisions

- Status: `ready`
- Domain: signal
- Source: `src/domain/signal/trade_decision.py`, `src/application/usecases/trade/execute_trade_usecase.py`

## 목적

시그널을 실제 거래 행동으로 변환한 결과를 저장한다. 주문 요청이 어떤 판단에서 시작됐는지 감사하기 위한 연결점이다.

## 저장 단위

한 row는 하나의 `TradeDecision`이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| decision_id | text | yes | 거래 판단 식별자. |
| signal_id | text | yes | 판단에 사용한 `signals.signal_id`. |
| action | text | yes | `enter_long`, `enter_short`, `exit`, `hold`. |
| generated_signal_id | text | no | 상위 `generated_signals.generated_signal_id`. |
| metadata | json | no | 변환 규칙, 유스케이스 실행 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `decision_id`
- FK 후보: `signal_id -> signals.signal_id`
- Index: `(action, reg_ymd, reg_dt)`
- Check: `action IN ('enter_long', 'enter_short', 'exit', 'hold')`, `use_yn IN ('Y', 'N')`
