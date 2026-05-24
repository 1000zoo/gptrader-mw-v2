# indicator_values

- Status: `ready`
- Domain: indicator
- Source: `src/domain/indicator/indicator_value.py`, `src/domain/indicator/indicator_set.py`

## 목적

정규화된 지표 이름, 파라미터, 계산 값을 저장한다. 전략 입력 감사와 지표별 조회에 사용한다.

## 저장 단위

한 row는 하나의 `IndicatorValue`다. `indicator_set_id + indicator_key`는 유일해야 한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| indicator_value_id | text | yes | 지표 값 식별자. |
| indicator_set_id | text | yes | 소속 `indicator_sets.indicator_set_id`. |
| symbol | text | yes | 조회 최적화를 위한 중복 컬럼. |
| timeframe | text | yes | 조회 최적화를 위한 중복 컬럼. |
| measured_at | timestamptz | yes | 계산 기준 시각. |
| indicator_name | text | yes | 정규화된 지표 이름. 예: `rsi`. |
| indicator_key | text | yes | 이름과 파라미터를 합친 정규화 키. 예: `rsi.period_14`. |
| value | numeric | yes | 계산 결과 값. |
| parameters | json | no | 지표 파라미터. 예: `{"period":14}`. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `indicator_value_id`
- Unique: `(indicator_set_id, indicator_key)`
- Index: `(symbol, timeframe, indicator_key, reg_ymd, measured_at)`
- Check: `indicator_name <> ''`, `indicator_key <> ''`, `use_yn IN ('Y', 'N')`
