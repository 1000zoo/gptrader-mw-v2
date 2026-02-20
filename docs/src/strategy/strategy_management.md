# Strategy Module: Strategy Management

## 개요

전략 실행 인터페이스(`IStrategy`)와 별도로, 전략 메타정보를 DB에 저장하고 런타임에 동적으로 로딩하는 관리 모듈을 추가했다.

핵심 목적:
- 전략 등록/조회/수정/삭제(CRUD)
- `strategy_name` 기반 활성 전략 조회(`use_yn = 'Y'`)
- `importlib`를 사용한 전략 클래스 동적 import 및 인스턴스 생성

## 구현 위치

- VO
  - `src/strategy/vo/strategy/default.py`
  - `src/strategy/vo/strategy/filter.py`
- Repository
  - `src/strategy/repository/strategy/strategy_repo.py`
- Service
  - `src/strategy/service/strategy/strategy_service.py`
- DB 스키마
  - `sql/011_create_strategy.sql`
  - `sql/create_table.sql` (통합 스키마 반영)

## 데이터 모델 (VO)

### DefaultStrategyVo

공통 `Vo`(`src.common.model.base.Vo`) 상속.

필수 속성:
- `strategy_name`
- `module_path`
- `module_name`
- `use_yn`

추가 속성:
- `id`
- `description`
- `params` (JSON 직렬화 대상 dict)
- `version`
- `priority`
- `attr1` ~ `attr10`
- `reg_dt`, `upd_dt`

### StrategyFilterVo

조회 조건 VO:
- `id`, `strategy_name`, `module_path`, `module_name`, `use_yn`, `version`, `priority`

## Repository 기능

`StrategyRepository` 제공 메서드:
- `insert_strategy(vo)`
- `select_strategies(filter_vo)`
- `select_strategy_by_name(strategy_name, only_active=True)`
- `update_strategy(vo)`
- `delete_strategy(strategy_name)`

구현 포인트:
- `update_strategy`는 `strategy_name`을 키로 사용
- `only_active=True`일 때 `use_yn='Y'` 조건으로 조회
- 공용 DB 유틸 허용 테이블에 `strategy` 추가 (`src/common/db/util.py`)

## Service 기능

`StrategyService` 제공 메서드:
- CRUD
  - `create_strategy`
  - `find_strategies`
  - `find_strategy_by_name`
  - `update_strategy`
  - `delete_strategy`
- 관리 기능
  - `build_strategy_instance(strategy_name)`

### build_strategy_instance 동작

1. `strategy_name` + 활성 조건(`use_yn='Y'`)으로 전략 메타 조회
2. `importlib.import_module(module_path)`로 모듈 import
3. `module_name` 클래스 조회
4. `IStrategy` 상속 여부 검증
5. 클래스 인스턴스 생성 후 반환

예외 처리:
- 전략 미존재: `DataNotFoundException`
- import/클래스 검증/생성 실패: `InvalidRequestException`
- DB 처리 실패: `RepositoryError`

## DB 스키마

`strategy` 테이블 컬럼:
- 기본: `id`, `strategy_name`, `module_path`, `module_name`, `use_yn`
- 확장: `description`, `params(JSONB)`, `version`, `priority`
- 공통: `attr1~attr10`, `reg_dt`, `upd_dt`

인덱스:
- `ux_strategy_name` (유니크)
- `idx_strategy_use_yn`

## 테스트

추가 테스트:
- `tests/test_strategy_service.py`
  - 활성 전략 로딩 성공
  - 전략 미존재 실패
  - 잘못된 클래스 타입 실패
- `tests/test_strategy_schema.py`
  - `sql/011_create_strategy.sql` 존재 및 필수 컬럼 확인

## 사용 예시

```python
from src.strategy.service.strategy.strategy_service import StrategyService

service = StrategyService()
strategy = await service.build_strategy_instance("my_strategy")
```

DB에 등록된 `module_path`, `module_name`이 올바르면 런타임에서 전략 클래스를 동적으로 생성할 수 있다.
