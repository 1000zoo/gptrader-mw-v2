# exposure_limits

- Status: `ready`
- Domain: risk
- Source: `src/domain/risk/exposure_limit.py`, `src/application/usecases/trade/dto.py`

## 목적

거래 실행 시점의 계좌/심볼 노출 한도 입력을 저장한다. 주문이 어떤 한도 조건에서 허용 또는 차단됐는지 감사한다.

## 저장 단위

한 row는 하나의 `ExposureLimit` snapshot이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| exposure_limit_id | text | yes | 노출 한도 snapshot 식별자. |
| symbol | text | no | 심볼별 한도인 경우 대상 심볼. 총량 한도만이면 비어 있을 수 있다. |
| equity | numeric | yes | 계좌 equity. 0보다 커야 한다. |
| current_total_exposure | numeric | yes | 현재 총 노출. 0 이상. |
| current_symbol_exposure | numeric | yes | 현재 심볼 노출. 0 이상. |
| max_total_exposure_ratio | numeric | yes | 총 노출 최대 비율. 0보다 커야 한다. |
| max_symbol_exposure_ratio | numeric | yes | 심볼 노출 최대 비율. 0보다 커야 한다. |
| metadata | json | no | 계좌 출처, 계산 기준 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `exposure_limit_id`
- Index: `(symbol, reg_ymd, reg_dt)`
- Check: numeric 값의 도메인 불변조건, `use_yn IN ('Y', 'N')`
