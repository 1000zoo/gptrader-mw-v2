# Module E: `src/domain/signal_generator`

## 목적

여러 전략을 조합해 최종 시그널을 만드는 상위 도메인 규칙을 정의한다.

## 책임

- 시그널 생성기 인터페이스 정의
- 단일 전략, 복합 전략, 레짐 기반 생성기 경계 정의
- 전략 결과를 최종 시그널로 변환하는 규칙 정의

## 포함 범위

- `src/domain/signal_generator/signal_generator.py`
- `src/domain/signal_generator/composite_signal_generator.py`
- `src/domain/signal_generator/regime_signal_generator.py`

## 제외 범위

- 실제 전략 저장소 조회
- 백테스트 흐름
- 주문 실행 흐름

## 선행 조건

- Module C
- Module D

## 산출물

- 생성기 인터페이스
- 전략 조합 방식 초안
- 시그널 집계 진입점

## 완료 기준

- 단일 전략과 복합 전략을 동일한 방식으로 호출할 수 있다.
- 후속 lifecycle 모듈이 조합 정의를 연결할 수 있다.
- application 레이어가 내부 전략 조합 세부사항을 몰라도 된다.

## 다음 연결 모듈

- Module I
- Module K
- Module L
