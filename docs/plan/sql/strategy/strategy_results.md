# strategy_results

- Status: `done`
- Domain: strategy
- Source: `src/domain/strategy/strategy_result.py`, `src/domain/signal_generator/signal_generator.py`

## 목적

복합 시그널 생성 과정에서 개별 전략이 낸 판단 결과를 저장한다. 최종 시그널과 개별 전략 시그널을 분리 분석하기 위한 테이블이다.

## 저장 단위

한 row는 하나의 `StrategyResult`다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| result_id | text | yes | 전략 결과 식별자. |
| generated_signal_id | text | no | 상위 `generated_signals.generated_signal_id`. 단독 백테스트 결과는 비어 있을 수 있다. |
| target_id | text | no | research/lifecycle 대상 id. |
| strategy_name | text | yes | `StrategyResult.name`. |
| signal_id | text | yes | 결과가 참조하는 `signals.signal_id`. |
| metadata | json | no | 전략 결과 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `result_id`
- FK 후보: `signal_id -> signals.signal_id`
- Index: `(strategy_name, reg_ymd, reg_dt)`
- Index: `(generated_signal_id, strategy_name)`
- Check: `strategy_name <> ''`, `use_yn IN ('Y', 'N')`
