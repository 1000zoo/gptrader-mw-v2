# SQL Assets

이 디렉토리는 DB 스키마 DDL의 기준 위치다. 에이전트가 테이블, 인덱스, 제약조건을 생성하거나 수정할 때는 이 디렉토리를 먼저 확인하고 함께 갱신한다.

## Structure

- `ddl/<domain>/tables/`: 도메인별 테이블 `CREATE TABLE` DDL
- `ddl/<domain>/indexes/`: 도메인별 테이블 또는 기능별 인덱스 DDL
- `ddl/<domain>/constraints/`: 도메인별 FK, CHECK, UNIQUE 등 별도 제약조건 DDL
- `tests/`: DDL 검증 SQL, 스키마 점검 쿼리
- `plans/`: 스키마 변경 계획, 마이그레이션 전 확인 사항
- `seeds/`: 기준 데이터 또는 로컬 개발용 seed SQL

## Required Table Columns

모든 테이블 DDL은 아래 공통 컬럼을 포함해야 한다.

- `reg_ymd`: 생성일, `YYYYMMDD` 포맷 문자열
- `reg_dt`: 생성 일시, datetime/timestamp 타입
- `upd_dt`: 수정 일시, datetime/timestamp 타입
- `use_yn`: 사용 여부, `Y` 또는 `N`만 허용

## SQLite Type Mapping

SQLite에는 별도 boolean storage class가 없으므로, plan 문서의 `boolean` 컬럼은 `INTEGER`로 저장하고 `CHECK (<column> IN (0, 1))` 제약으로 제한한다. `0`은 false, `1`은 true를 의미한다.

## Agent Checklist

DDL을 생성하거나 수정할 때 아래를 확인한다.

- 테이블 DDL에 공통 컬럼 4개가 모두 있는가
- `use_yn` 값이 `Y`, `N`으로 제한되는가
- PK, FK, UNIQUE, CHECK 제약조건이 필요한 만큼 정의되었는가
- 조회 조건, 조인 조건, 정렬 조건에 필요한 인덱스를 검토했는가
- 인덱스에 가능한 한 `reg_ymd`를 포함했는가
- 테이블 변경에 맞춰 같은 도메인의 `ddl/<domain>/indexes`, `ddl/<domain>/constraints`, `tests`를 함께 확인했는가
- DB 세부사항이 `domain` 또는 `application` 레이어로 새지 않는가

## Naming

파일명은 테이블명 또는 대상 책임을 기준으로 정한다.

- 테이블 DDL: `ddl/<domain>/tables/<table_name>.sql`
- 인덱스 DDL: `ddl/<domain>/indexes/<table_name>_indexes.sql`
- 제약조건 DDL: `ddl/<domain>/constraints/<table_name>_constraints.sql`
