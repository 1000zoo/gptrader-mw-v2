# research_runs

- Status: `done`
- Domain: application
- Source: `src/application/usecases/research/*.py`, `src/application/usecases/research/dto.py`

## 목적

백테스트와 드라이런 연구 실행의 입력/출력 경계를 저장한다. 전략 평가 재현과 lifecycle 평가 연결에 사용한다.

## 저장 단위

한 row는 하나의 `BacktestStrategyUseCase` 또는 `DryRunStrategyUseCase` 실행이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| research_run_id | text | yes | 연구 실행 식별자. |
| target_id | text | yes | 전략 또는 generator 대상 id. |
| mode | text | yes | `backtest` 또는 `dry_run`. |
| symbol | text | yes | 실행 심볼. |
| timeframe | text | yes | 실행 타임프레임. |
| candle_limit | integer | yes | 요청 캔들 개수. |
| snapshot_id | text | no | 사용한 `market_snapshots.snapshot_id`. |
| indicator_set_id | text | no | 사용한 `indicator_sets.indicator_set_id`. |
| strategy_result_id | text | no | 백테스트 전략 결과 id. |
| generated_signal_id | text | no | 드라이런 생성 시그널 id. |
| evaluation_id | text | no | 후속 `strategy_evaluations.evaluation_id`. |
| metadata | json | no | command metadata와 실행 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `research_run_id`
- Index: `(target_id, mode, reg_ymd, reg_dt)`
- Index: `(symbol, timeframe, reg_ymd, reg_dt)`
- Check: `mode IN ('backtest', 'dry_run')`, `candle_limit > 0`, `use_yn IN ('Y', 'N')`
