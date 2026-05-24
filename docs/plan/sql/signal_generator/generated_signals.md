# generated_signals

- Status: `ready`
- Domain: signal_generator
- Source: `src/domain/signal_generator/signal_generator.py`, `src/domain/ports/signal_log_repository_port.py`

## 목적

시그널 생성기가 만든 최종 시그널과 개별 전략 결과 묶음을 저장한다. 실거래, 드라이런, 백테스트 결과의 상위 집계 단위다.

## 저장 단위

한 row는 하나의 `GeneratedSignal`이다. 최종 시그널은 `signal_id`로 연결하고, 개별 전략 결과는 `strategy_results`가 참조한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| generated_signal_id | text | yes | 생성 시그널 식별자. |
| generator_id | text | no | 생성에 사용한 generator id. |
| signal_id | text | yes | 최종 `signals.signal_id`. |
| strategy_result_count | integer | yes | 포함된 개별 전략 결과 수. |
| context_snapshot_id | text | no | 사용한 `market_snapshots.snapshot_id`. |
| indicator_set_id | text | no | 사용한 `indicator_sets.indicator_set_id`. |
| metadata | json | no | 생성기 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `generated_signal_id`
- FK 후보: `signal_id -> signals.signal_id`
- Index: `(generator_id, reg_ymd, reg_dt)`
- Check: `strategy_result_count >= 0`, `use_yn IN ('Y', 'N')`
