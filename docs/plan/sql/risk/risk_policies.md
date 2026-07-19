# risk_policies

- Status: `done`
- Domain: risk
- Source: `src/domain/risk/risk_policy.py`

## 목적

리스크 검사 정책의 버전과 적용 범위를 저장한다. 현재 `RiskPolicy`는 상태 없는 기본 정책이지만, 운영 중 정책 교체와 감사 추적을 위해 별도 기준 테이블을 둔다.

## 저장 단위

한 row는 하나의 리스크 정책 버전이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| policy_id | text | yes | 리스크 정책 식별자. |
| version | text | yes | 정책 버전. |
| name | text | yes | 운영 표시명. |
| implementation | text | no | 정책 구현 경로 또는 구현 키. |
| rules | json | no | 정책 파라미터와 규칙 설명. 현재 기본 정책은 비어 있을 수 있다. |
| metadata | json | no | 작성자, 설명, 적용 범위 등 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `policy_id`
- Unique 후보: `version`
- Index: `(reg_ymd, version)`
- Check: `policy_id <> ''`, `version <> ''`, `name <> ''`, `use_yn IN ('Y', 'N')`
