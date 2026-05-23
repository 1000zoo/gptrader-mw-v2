# Module O: `src/infrastructure/persistence`

## 목적

도메인 저장소 포트를 실제 DB 계층으로 구현할 구조를 정리한다.

## 책임

- 저장소 구현
- 영속화 모델 정의
- 마이그레이션 관리 기준 정의
- `./sql` 기반 테이블별 DDL, 인덱스, 제약조건 관리 기준 정의

## 포함 범위

- `src/infrastructure/persistence/repositories/`
- `src/infrastructure/persistence/models/`
- `src/infrastructure/persistence/migrations/`
- `sql/ddl/tables/`
- `sql/ddl/indexes/`
- `sql/ddl/constraints/`
- `sql/tests/`
- `sql/plans/`
- `sql/seeds/`

## 제외 범위

- 도메인 규칙
- 유스케이스 흐름
- API 응답 형식

## 선행 조건

- Module I
- Module J

## 산출물

- 저장소 구현 구조
- 도메인 모델과 영속 모델 매핑 기준
- 주요 테이블 범위 초안
- 테이블별 DDL 파일 관리 기준
- 테이블별 인덱스와 제약조건 관리 기준
- DDL 변경 시 에이전트 체크리스트

## 완료 기준

- lifecycle, signal log, evaluation 저장 대상이 정리된다.
- DB 세부사항이 application 레이어로 노출되지 않는다.
- 마이그레이션 관리 위치가 고정된다.
- `./sql` 아래에서 테이블 DDL, 인덱스, 제약조건, SQL 테스트 위치가 고정된다.
- 모든 테이블 DDL에 `reg_ymd`, `reg_dt`, `upd_dt`, `use_yn` 공통 컬럼이 포함되도록 기준이 문서화된다.
- `use_yn`은 `Y`, `N` 두 값만 허용하도록 DDL 체크리스트에 포함된다.
- 인덱스 정의에는 가능한 한 `reg_ymd`를 포함하도록 기준이 문서화된다.

## 다음 연결 모듈

- Module K
- Module L
- Module M
