# strategy_lifecycle_runs

- Status: `done`
- Domain: application
- Source: `src/application/usecases/strategy_lifecycle/*.py`, `src/application/usecases/strategy_lifecycle/dto.py`

## 목적

전략 등록, 평가 기반 승격, lifecycle 실행 결과를 저장한다. 어떤 정책과 평가가 승격 결과를 만들었는지 추적한다.

## 저장 단위

한 row는 하나의 lifecycle application 실행이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| lifecycle_run_id | text | yes | lifecycle 실행 식별자. |
| run_type | text | yes | `register`, `promote`, `run_lifecycle`. |
| target_id | text | no | 전략 또는 generator 대상 id. |
| strategy_id | text | no | 등록된 strategy id. |
| generator_id | text | no | 등록된 generator id. |
| source_evaluation_id | text | no | 승격 판단 대상 평가 id. |
| promoted_evaluation_id | text | no | 생성된 promoted 평가 id. |
| policy_id | text | no | 사용한 `promotion_policies.policy_id`. |
| promoted | boolean | no | 승격 성공 여부. |
| reason | text | no | 승격 또는 거절 사유. |
| metadata | json | no | command/result 원본 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `lifecycle_run_id`
- Index: `(target_id, run_type, reg_ymd, reg_dt)`
- Index: `(source_evaluation_id, promoted_evaluation_id)`
- Check: `run_type IN ('register', 'promote', 'run_lifecycle')`, `use_yn IN ('Y', 'N')`
