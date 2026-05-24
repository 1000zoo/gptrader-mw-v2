# signal_generator_strategy_links

- Status: `ready`
- Domain: signal_generator
- Source: `src/domain/lifecycle/signal_generator_definition.py`

## 목적

시그널 생성기 정의가 포함하는 전략 목록을 순서 보존 방식으로 저장한다. `payload` 조회 없이 generator와 strategy 관계를 분석할 수 있게 한다.

## 저장 단위

한 row는 하나의 generator-strategy 연결이다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| generator_id | text | yes | `signal_generator_definitions.generator_id`. |
| strategy_id | text | yes | `strategy_definitions.strategy_id`. |
| sequence_no | integer | yes | generator 내부 전략 순서. 1부터 증가한다. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `(generator_id, strategy_id)`
- Unique: `(generator_id, sequence_no)`
- FK 후보: `generator_id -> signal_generator_definitions.generator_id`
- FK 후보: `strategy_id -> strategy_definitions.strategy_id`
- Check: `sequence_no > 0`, `use_yn IN ('Y', 'N')`
