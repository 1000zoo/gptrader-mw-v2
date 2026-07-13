# position_sizer_configs

- Status: `done`
- Domain: risk
- Source: `src/domain/risk/position_sizer.py`, `src/application/usecases/trade/dto.py`

## 목적

포지션 크기를 계산한 설정값을 버전 단위로 저장한다. `base_risk_ratio`, `leverage` 변경이 주문 수량에 미친 영향을 감사한다.

## 저장 단위

한 row는 하나의 `PositionSizer` 설정이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| config_id | text | yes | 설정 식별자. |
| version | text | yes | 설정 버전. |
| base_risk_ratio | numeric | yes | 기본 리스크 비율. 0보다 커야 한다. |
| leverage | numeric | yes | 레버리지. 0보다 커야 한다. |
| metadata | json | no | 적용 범위, 작성자 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `config_id`
- Unique 후보: `version`
- Index: `(reg_ymd, version)`
- Check: `base_risk_ratio > 0`, `leverage > 0`, `use_yn IN ('Y', 'N')`
