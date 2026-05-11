# Module I: `src/domain/lifecycle`

## 목적

전략 생성부터 평가와 승격까지의 수명주기 모델을 정의한다.

## 책임

- 전략 정의 모델 정의
- 시그널 생성기 조합 정의 모델 정의
- 평가 결과와 승격 정책 정의

## 포함 범위

- `src/domain/lifecycle/strategy_definition.py`
- `src/domain/lifecycle/signal_generator_definition.py`
- `src/domain/lifecycle/strategy_evaluation.py`
- `src/domain/lifecycle/promotion_policy.py`

## 제외 범위

- 실제 백테스트 엔진 구현
- DB 스키마 구현
- 스케줄러 실행

## 선행 조건

- Module C
- Module D
- Module E

## 산출물

- 전략 등록 모델
- 조합 설정 모델
- 승격 기준 모델

## 완료 기준

- persistence 모듈이 저장 대상으로 삼을 모델이 정리된다.
- research/application 모듈이 동일한 상태 언어를 사용한다.
- 조합 정책이 전략 자체와 분리된다.

## 다음 연결 모듈

- Module J
- Module L
- Module M
- Module O
