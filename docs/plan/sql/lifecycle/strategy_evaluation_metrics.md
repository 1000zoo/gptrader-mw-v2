# strategy_evaluation_metrics

- Status: `done`
- Domain: lifecycle
- Source: `src/domain/lifecycle/strategy_evaluation.py`, `src/domain/lifecycle/promotion_policy.py`

## 목적

평가 지표를 이름별 numeric row로 분리해 승격 정책과 리포팅에서 직접 조회할 수 있게 한다.

## 저장 단위

한 row는 하나의 평가 지표다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| metric_id | text | yes | 평가 지표 식별자. |
| evaluation_id | text | yes | `strategy_evaluations.evaluation_id`. |
| metric_name | text | yes | 지표명. 예: `sharpe`, `win_rate`. |
| metric_value | numeric | yes | 지표 값. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `metric_id`
- Unique: `(evaluation_id, metric_name)`
- FK 후보: `evaluation_id -> strategy_evaluations.evaluation_id`
- Index: `(metric_name, reg_ymd, metric_value)`
- Check: `metric_name <> ''`, `use_yn IN ('Y', 'N')`
