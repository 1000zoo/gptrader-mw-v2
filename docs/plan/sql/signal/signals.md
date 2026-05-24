# signals

- Status: `ready`
- Domain: signal
- Source: `src/domain/signal/signal.py`

## 목적

전략, 시그널 생성기, 거래 판단에서 공통으로 사용하는 최종 방향과 신뢰도를 조회 가능한 형태로 저장한다.

## 저장 단위

한 row는 하나의 `Signal`이다. 사유는 `signal_reasons`에 분리하고, 부가 정보는 `metadata`에 보관한다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| signal_id | text | yes | 시그널 식별자. |
| direction | text | yes | `long`, `short`, `wait`. |
| confidence | numeric | yes | 0 이상 1 이하의 신뢰도. |
| metadata | json | no | 전략별 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `signal_id`
- Index: `(direction, reg_ymd, reg_dt)`
- Check: `direction IN ('long', 'short', 'wait')`, `confidence BETWEEN 0 AND 1`, `use_yn IN ('Y', 'N')`
