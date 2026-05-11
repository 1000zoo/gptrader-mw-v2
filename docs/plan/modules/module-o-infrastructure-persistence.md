# Module O: `src/infrastructure/persistence`

## 목적

도메인 저장소 포트를 실제 DB 계층으로 구현할 구조를 정리한다.

## 책임

- 저장소 구현
- 영속화 모델 정의
- 마이그레이션 관리 기준 정의

## 포함 범위

- `src/infrastructure/persistence/repositories/`
- `src/infrastructure/persistence/models/`
- `src/infrastructure/persistence/migrations/`

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

## 완료 기준

- lifecycle, signal log, evaluation 저장 대상이 정리된다.
- DB 세부사항이 application 레이어로 노출되지 않는다.
- 마이그레이션 관리 위치가 고정된다.

## 다음 연결 모듈

- Module K
- Module L
- Module M
