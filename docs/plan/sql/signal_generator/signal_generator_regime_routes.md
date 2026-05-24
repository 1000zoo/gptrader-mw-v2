# signal_generator_regime_routes

- Status: `ready`
- Domain: signal_generator
- Source: `src/domain/lifecycle/signal_generator_definition.py`, `src/domain/signal_generator/regime_signal_generator.py`

## 목적

레짐 값별 위임 전략 또는 하위 생성기 라우팅을 저장한다. 레짐 기반 전략 운영 시 어떤 레짐이 어떤 전략에 연결됐는지 조회한다.

## 저장 단위

한 row는 하나의 regime route다.

## 컬럼

| Column | Type | Required | Definition |
|--------|------|----------|------------|
| route_id | text | yes | 라우트 식별자. |
| generator_id | text | yes | `signal_generator_definitions.generator_id`. |
| regime | text | yes | 컨텍스트 metadata에서 읽는 레짐 값. |
| strategy_id | text | yes | 라우팅 대상 전략 id. 현재 정의 모델은 전략 id를 값으로 갖는다. |
| metadata_key | text | no | 레짐을 읽는 metadata key. 기본값 후보는 `regime`. |
| reg_ymd | text | yes | 등록일 `YYYYMMDD`. |
| reg_dt | timestamptz | yes | 등록 시각. |
| upd_dt | timestamptz | yes | 수정 시각. |
| use_yn | text | yes | 사용 여부. `Y` 또는 `N`. |

## 키와 인덱스

- PK: `route_id`
- Unique: `(generator_id, regime)`
- FK 후보: `generator_id -> signal_generator_definitions.generator_id`
- FK 후보: `strategy_id -> strategy_definitions.strategy_id`
- Check: `regime <> ''`, `strategy_id <> ''`, `use_yn IN ('Y', 'N')`
