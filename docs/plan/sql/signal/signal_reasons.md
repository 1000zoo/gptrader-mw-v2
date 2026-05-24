# signal_reasons

- Status: `ready`
- Domain: signal
- Source: `src/domain/signal/signal_reason.py`

## 목적

시그널의 판단 사유를 코드 단위로 저장한다. 진입/대기 사유 분석과 운영 리포팅에 사용한다.

## 저장 단위

한 row는 하나의 `SignalReason`이다. 하나의 시그널은 여러 사유를 가질 수 있다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| reason_id | text | yes | 사유 식별자. |
| signal_id | text | yes | `signals.signal_id`. |
| sequence_no | integer | yes | 시그널 내부 사유 순서. |
| code | text | yes | 사유 코드. 빈 값 불가. |
| message | text | yes | 사람이 읽을 수 있는 사유 설명. 빈 값 불가. |
| metadata | json | no | 사유별 부가 정보. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `reason_id`
- FK 후보: `signal_id -> signals.signal_id`
- Unique: `(signal_id, sequence_no)`
- Index: `(code, reg_ymd, reg_dt)`
- Check: `sequence_no > 0`, `code <> ''`, `message <> ''`, `use_yn IN ('Y', 'N')`
