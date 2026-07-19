# Module M: `src/application/usecases/strategy_lifecycle`

## 목적

전략 등록, 평가 요청, 승격 결정 흐름을 하나의 운영 경계로 정리한다.

## 책임

- 전략 등록 유스케이스 정의
- 승격 유스케이스 정의
- 수명주기 실행 유스케이스 정의

## 포함 범위

- `src/application/usecases/strategy_lifecycle/register_strategy_usecase.py`
- `src/application/usecases/strategy_lifecycle/promote_strategy_usecase.py`
- `src/application/usecases/strategy_lifecycle/run_strategy_lifecycle_usecase.py`

## 제외 범위

- 백테스트 계산 자체
- 실제 알림 전송
- 스케줄러 등록

## 선행 조건

- Module I
- Module J
- Module L

## 산출물

- 수명주기 오케스트레이션 경계
- 연구 결과와 운영 승격 사이 연결 규칙
- 상태 전이 흐름

## 완료 기준

- 전략 등록부터 승격까지 흐름이 유스케이스 단위로 분리된다.
- research 결과와 persistence 요구사항이 연결 가능하다.
- interfaces 레이어가 호출 가능한 운영 유스케이스가 생긴다.

## 다음 연결 모듈

- Module R
- Module S
