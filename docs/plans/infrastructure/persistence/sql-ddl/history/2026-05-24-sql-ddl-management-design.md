# SQL DDL Management Design

## Goal

프로젝트 루트의 `./sql` 아래에서 테이블별 DDL, 인덱스, 제약조건, SQL 검증 자산을 일관되게 관리한다.

## Design

`./sql`은 DB 스키마 정의의 기준 위치다. `src/infrastructure/persistence`는 저장소 구현, ORM/영속 모델, 마이그레이션 적용 로직을 담당하고, 테이블 생성문과 인덱스 정의 같은 원본 DDL은 `./sql`에서 관리한다.

디렉토리는 코드와 테스트, 계획을 나누는 프로젝트 구조와 유사하게 `ddl`, `tests`, `plans`로 나눈다. `ddl` 아래는 다시 `tables`, `indexes`, `constraints`로 분리해 테이블별 정의와 보조 정의가 섞이지 않게 한다.

## Rules

모든 테이블 DDL은 아래 공통 컬럼을 가져야 한다.

- `reg_ymd`: 생성일, `YYYYMMDD` 포맷 문자열
- `reg_dt`: 생성 일시, datetime/timestamp 타입
- `upd_dt`: 수정 일시, datetime/timestamp 타입
- `use_yn`: 사용 여부, `Y` 또는 `N`만 허용

DDL을 생성하거나 수정하는 에이전트는 테이블 정의, 인덱스 정의, 제약조건, 공통 컬럼 체크리스트를 함께 확인해야 한다.

