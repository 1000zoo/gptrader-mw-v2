# Module D: `src/domain/strategy`

## 목적

개별 전략이 어떤 입력을 받아 어떤 판단을 반환하는지 계약을 고정한다.

## 책임

- 전략 인터페이스 정의
- 전략 실행 컨텍스트 정의
- 전략 구현이 따라야 할 입력/출력 경계 정의

## 포함 범위

- `src/domain/strategy/strategy.py`
- `src/domain/strategy/strategy_context.py`
- `src/domain/strategy/strategy_result.py`
- `src/domain/strategy/implementations/`

## 제외 범위

- 전략 조합
- 유스케이스 오케스트레이션
- LLM 인프라 호출 상세

## 선행 조건

- Module A
- Module B
- Module C

## 산출물

- 기본 전략 인터페이스
- 타임프레임별 입력 컨텍스트
- 전략 구현 디렉토리 기준

## 완료 기준

- 새로운 전략이 기존 코드 수정 없이 추가 가능하다.
- 입력 컨텍스트가 전략 구현에 충분하다.
- 전략 결과가 Module C 계약을 따른다.

## 다음 연결 모듈

- Module E
- Module I
- Module L
