# promotion_policies

- Status: `ready`
- Domain: lifecycle/risk
- Source: `src/domain/lifecycle/promotion_policy.py`, `src/application/usecases/strategy_lifecycle/dto.py`

## 목적

전략 승격 기준을 버전별로 저장한다. 어떤 평가가 어떤 기준으로 승격 또는 거절됐는지 추적한다.

## 저장 단위

한 row는 하나의 `PromotionPolicy` 설정이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| policy_id | text | yes | 승격 정책 식별자. |
| version | text | yes | 정책 버전. |
| minimum_metrics | json | yes | 지표별 최소 기준값. Decimal은 문자열로 저장한다. |
| allowed_statuses | json | yes | 승격 가능한 평가 상태 목록. |
| metadata | json | no | 정책 설명, 적용 범위 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `policy_id`
- Unique 후보: `version`
- Index: `(reg_ymd, version)`
- Check: `version <> ''`, `minimum_metrics` not empty, `allowed_statuses` not empty, `use_yn IN ('Y', 'N')`
