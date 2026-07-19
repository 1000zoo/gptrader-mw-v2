# indicator_sets

- Status: `done`
- Domain: indicator
- Source: `src/domain/indicator/indicator_set.py`, `src/domain/strategy/strategy_context.py`

## 목적

한 심볼/타임프레임/측정 시각에 계산된 지표 묶음을 저장한다. 전략 입력 재현과 지표 캐시의 상위 단위다.

## 저장 단위

한 row는 하나의 `IndicatorSet` 헤더다. 실제 지표 값은 `indicator_values`에 저장한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| indicator_set_id | text | yes | 지표 묶음 식별자. |
| symbol | text | yes | 지표 대상 심볼. |
| timeframe | text | yes | 지표 대상 타임프레임. |
| measured_at | timestamptz | yes | 지표 묶음 기준 시각. 최신 캔들의 `closed_at`과 맞아야 한다. |
| value_count | integer | yes | 포함 지표 값 수. 0 이상. |
| source_snapshot_id | text | no | 지표 계산에 사용한 `market_snapshots.snapshot_id`. |
| metadata | json | no | 계산 엔진, 버전 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `indicator_set_id`
- Unique 후보: `(symbol, timeframe, measured_at, source_snapshot_id)`
- Index: `(symbol, timeframe, reg_ymd, measured_at)`
- Check: `value_count >= 0`, `use_yn IN ('Y', 'N')`
