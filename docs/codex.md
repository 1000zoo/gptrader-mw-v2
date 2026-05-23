# Gptrader V3 Agent Charter

이 문서는 `gptrader v3`에서 작업하는 모든 에이전트의 공통 운영 헌장이다.
아키텍처 원칙, 작업 시작 절차, 상태 갱신 규칙, 모듈 경계 규칙을 한 문서에 통합한다.

## 1. 이 프로젝트에서 가장 먼저 할 일

어떤 에이전트든 작업을 시작하기 전에 아래 순서를 반드시 따른다.

1. `docs/codex.md`를 읽는다.
2. `docs/progress.md`를 읽는다.
3. `docs/plan/modules/README.md`를 읽는다.
4. 자신이 맡을 모듈의 상세 문서를 읽는다.
5. `docs/progress.md`에서 해당 모듈 상태를 `in progress`로 바꾼다.
6. 그 뒤에만 구현, 수정, 테스트를 시작한다.

이 순서를 건너뛰면 안 된다.

## 2. 프로젝트 목표

이 프로젝트의 목표는 아래 조건을 만족하는 크립토 선물 트레이딩 시스템을 만드는 것이다.

- 단일 전략이 아니라 여러 전략을 지원한다.
- 전략 교체와 조합이 쉬워야 한다.
- 필요할 때 LLM 기반 판단을 붙일 수 있어야 한다.
- 실거래, 백테스트, 드라이런, 전략 승격을 분리된 경계로 다뤄야 한다.

`v2-backup`은 참고 자료일 뿐이며, `v3`는 구조적으로 이어받는 프로젝트가 아니다.

## 3. 기준 문서

작업 중 판단이 필요하면 아래 우선순위를 따른다.

1. `docs/codex.md`
2. `docs/progress.md`
3. `docs/plan/plan.md`
4. `docs/plan/modules/*.md`
5. 로컬 코드
6. `v2-backup`

### 문서 역할

- `docs/codex.md`
  - 전체 운영 원칙
  - 아키텍처 제약
  - 에이전트 행동 규칙
- `docs/progress.md`
  - 현재 누가 무엇을 해야 하는지 보여주는 작업 보드
  - 상태 갱신의 단일 기준
- `docs/plan/plan.md`
  - 전체 모듈 구조와 병렬 진행 순서
- `docs/plan/modules/*.md`
  - 각 모듈의 상세 범위와 완료 기준

## 4. 작업 단위 원칙

- 작업 단위는 기본적으로 모듈 하나다.
- 한 세션은 하나의 모듈만 소유하는 것을 원칙으로 한다.
- 다른 모듈을 수정해야 하면 먼저 그 이유를 문서에 남긴다.
- 선행 계약이 없는 상태에서 하위 구현으로 내려가면 안 된다.
- 구현보다 먼저 경계와 책임을 고정한다.

## 5. 현재 모듈 운영 방식

모든 모듈 상세 계획은 `docs/plan/modules/` 아래에 있다.

예시:

- `docs/plan/modules/module-a-market.md`
- `docs/plan/modules/module-c-signal.md`
- `docs/plan/modules/module-k-application-trade.md`

각 모듈 문서는 최소한 아래 내용을 가진다.

- 목적
- 책임
- 포함 범위
- 제외 범위
- 선행 조건
- 산출물
- 완료 기준
- 다음 연결 모듈

에이전트는 이 범위를 벗어나지 않는 방향으로만 작업해야 한다.

## 6. Progress Board 규칙

`docs/progress.md`는 전체 작업 현황의 단일 진실 원본이다.

### 허용 상태

- `not started`
- `ready`
- `in progress`
- `blocked`
- `done`

### 상태 변경 규칙

- 작업 시작 전: `in progress`
- 작업 완료 후: `done`
- 선행 조건 미충족: `blocked`
- 아직 시작 전이지만 착수 가능: `ready`

### 작업 로그 규칙

에이전트는 작업이 끝나면 `docs/progress.md`의 작업 로그에 반드시 기록한다.

기본 형식:

```markdown
### YYYY-MM-DD Module X

- Agent: 담당 세션 또는 이름
- Status: `in progress` -> `done`
- Summary: 무엇을 했는지
- Follow-up: 다음 에이전트가 이어서 할 일
```

### 금지 사항

- 상태를 바꾸지 않고 작업 완료라고 주장하는 것
- 로그를 남기지 않고 다음 모듈로 넘어가는 것
- 다른 모듈의 상태를 임의로 `done` 처리하는 것

## 7. 아키텍처 원칙

최상위 레이어는 아래 네 개로 고정한다.

- `src/domain`
- `src/application`
- `src/infrastructure`
- `src/interfaces`

의존 방향은 아래처럼만 허용한다.

- `interfaces -> application -> domain`
- `infrastructure`는 상위 레이어 계약을 구현한다.

상위 레이어가 하위 concrete implementation을 직접 생성하면 안 된다.

## 8. 레이어별 규칙

### `domain`

허용:

- 엔티티
- 값 객체
- 비즈니스 규칙
- 정책
- 계산
- 포트 인터페이스

금지:

- 거래소 SDK 호출
- DB 접근
- ORM 타입
- HTTP 호출
- 직접 LLM 호출
- 유스케이스 흐름 오케스트레이션

### `application`

허용:

- 유스케이스 조립
- 입력 DTO 처리
- 도메인 호출 순서 정의
- 포트 호출

금지:

- 인프라 예외 타입 직접 분기
- 거래소 응답 구조 직접 해석
- DB 드라이버 세부사항 처리
- 도메인 규칙 장기 체류

### `infrastructure`

허용:

- 거래소 연동
- DB 구현
- 캐시
- 메신저
- LLM adapter
- 외부 응답 파싱
- 재시도/타임아웃/프로토콜 처리

금지:

- 도메인 의미 재정의
- 유스케이스 흐름 결정
- 컨트롤러 역할 수행

### `interfaces`

허용:

- API
- 스케줄러
- 웹소켓 진입점
- CLI

금지:

- 비즈니스 규칙 구현
- 인프라 세부 로직 구현
- 전략 판단 직접 수행

## 9. 네이밍 규칙

- 이름은 책임을 드러내야 한다.
- `Service`, `Helper`, `Util`, `Common`, `Manager` 같은 포괄 이름을 습관적으로 쓰지 않는다.
- 같은 역할이 아니면 같은 접미사를 남발하지 않는다.
- 파일명도 클래스명과 같은 수준으로 책임이 보여야 한다.

좋은 예:

- `signal_generator.py`
- `position_sizer.py`
- `promotion_policy.py`
- `order_execution_port.py`

나쁜 예:

- `signal_service.py`
- `common_helper.py`
- `position_manager.py`

## 10. 공유 모듈 규칙

- `utils`, `helpers`, `shared`, `common` 디렉토리는 기본적으로 만들지 않는다.
- 재사용된다는 이유만으로 공용 모듈로 올리지 않는다.
- 아래 네 조건을 모두 만족할 때만 승격한다.

1. 진짜로 여러 문맥에서 재사용된다.
2. 특정 도메인 문맥에 강하게 묶여 있지 않다.
3. 이름만 보고 책임이 분명하다.
4. 원래 모듈 밖으로 꺼내도 의미가 유지된다.

## 11. `v2-backup` 사용 규칙

- `v2-backup`은 참고 자료다.
- 구조는 복제하지 않는다.
- 객체 생성 방식은 복제하지 않는다.
- 도메인 의미가 여전히 유효할 때만 참고한다.
- 가져온 로직은 `v3` 경계에 맞게 다시 배치하고 테스트로 검증한다.

특히 아래는 그대로 들여오면 안 된다.

- 레이어를 흐리는 service 체인
- 직접 concrete class를 생성하는 usecase
- 벤더 세부사항이 섞인 도메인 로직
- 의미가 약한 공용 유틸 모듈

## 12. 의존성 주입 규칙

- `domain`과 `application`은 구현체를 직접 생성하면 안 된다.
- 생성자 주입 또는 명시적 composition root를 사용한다.
- 숨겨진 전역 singleton을 만들지 않는다.
- 테스트 편의를 위한 우회 생성도 기본 구조를 깨면 안 된다.

## 13. LLM 규칙

- LLM은 외부 의존성이다.
- `domain`과 `application`은 LLM 벤더를 알면 안 된다.
- 프롬프트 조립, 응답 파싱, 재시도, 타임아웃은 `infrastructure`에 둔다.
- 전략은 계약 기반 입력과 출력만 다룬다.

## 14. 에러 처리 규칙

- 에러는 레이어 언어로 번역해서 올린다.
- `application`은 DB/HTTP/SDK 예외를 직접 분기하면 안 된다.
- `infrastructure`가 외부 실패를 계약 언어로 바꾼다.
- `domain`은 인프라 장애를 표현하지 않는다.
- 로그만 남기고 삼키는 실패 처리는 금지한다.

## 15. 테스트 규칙

- 테스트는 의미 있는 동작을 검증해야 한다.
- 통과만 위한 테스트는 금지한다.
- 테스트 구조는 `src/` 구조를 따라간다.
- `domain`은 단위 테스트 중심으로 검증한다.
- `infrastructure`는 계약 테스트 또는 통합 테스트로 검증한다.
- 외부 의존성 mocking은 경계 검증을 위한 용도로만 쓴다.

## 16. SQL DDL 관리 규칙

`./sql`은 DB 스키마 DDL의 기준 위치다. `src/infrastructure/persistence`는 저장소 구현, 영속 모델, 마이그레이션 적용 로직을 담당하고, 테이블 생성문, 인덱스, 제약조건 같은 원본 DDL은 `./sql` 아래에서 관리한다.

### 디렉토리 기준

- `sql/ddl/tables/`: 테이블별 `CREATE TABLE` DDL
- `sql/ddl/indexes/`: 테이블별 또는 기능별 `CREATE INDEX` DDL
- `sql/ddl/constraints/`: 별도 관리가 필요한 FK, CHECK, UNIQUE 등 제약조건 DDL
- `sql/tests/`: DDL 검증용 SQL 또는 스키마 점검 쿼리
- `sql/plans/`: 스키마 변경 계획과 마이그레이션 전 확인 사항
- `sql/seeds/`: 기준 데이터 또는 로컬 개발용 seed SQL

### DDL 작성 체크리스트

DDL을 생성하거나 수정하는 에이전트는 아래 항목을 반드시 확인한다.

- 테이블 DDL에는 `reg_ymd`, `reg_dt`, `upd_dt`, `use_yn` 공통 컬럼이 모두 있어야 한다.
- `reg_ymd`는 생성일을 `YYYYMMDD` 포맷으로 저장하는 컬럼이다.
- `reg_dt`와 `upd_dt`는 datetime/timestamp 타입이어야 한다.
- `use_yn`은 `Y`, `N` 두 값만 허용해야 한다.
- 신규 테이블에는 필요한 PK, FK, UNIQUE, CHECK 제약조건을 명시해야 한다.
- 조회 조건, 조인 조건, 정렬 조건에 맞는 인덱스를 함께 검토해야 한다.
- 인덱스에는 가능한 한 `reg_ymd`를 포함해 날짜 기준 조회와 파티션성 접근을 지원해야 한다.
- 테이블 DDL을 바꾸면 관련 인덱스, 제약조건, SQL 테스트 또는 점검 쿼리도 같이 확인해야 한다.
- DB 세부사항은 `application` 또는 `domain` 레이어로 노출하면 안 된다.

## 17. 에이전트 시작 체크리스트

작업 시작 전 아래를 모두 확인한다.

- `docs/progress.md`에서 내가 맡을 모듈이 `ready` 또는 합리적으로 `not started`인지 확인했는가
- 선행 모듈이 완료 또는 계약 확정 상태인지 확인했는가
- 모듈 상세 문서를 읽었는가
- 범위 밖 수정이 필요한지 판단했는가
- 상태를 `in progress`로 바꿨는가

하나라도 아니면 구현을 시작하지 않는다.

## 18. 에이전트 종료 체크리스트

작업 종료 전 아래를 모두 확인한다.

- 내가 맡은 범위만 수정했는가
- 필요 테스트를 실행했는가
- 테스트를 못 돌렸다면 이유를 남겼는가
- `docs/progress.md` 상태를 갱신했는가
- 작업 로그를 남겼는가
- 다음 에이전트가 무엇을 해야 하는지 `Follow-up`에 적었는가

## 19. 빠른 시작 규칙

현재 바로 시작 가능한 우선 모듈은 `docs/progress.md`를 따른다.
새 에이전트는 기본적으로 아래 순서에서 선택한다.

1. `ready` 상태 모듈
2. 현재 우선순위 상단 모듈
3. 선행 의존성이 모두 충족된 모듈

모호하면 새로운 모듈을 임의로 열지 말고, 이미 `ready`인 모듈부터 진행한다.

## 20. 한 줄 원칙

이 프로젝트에서 에이전트는 코드를 먼저 쓰는 존재가 아니라, 문서화된 모듈 경계를 따라 안전하게 다음 작업을 이어가는 존재다.
