# Module C: `src/domain/signal`

## 목적

전략 판단과 최종 매매 판단의 공통 언어를 정의한다.

## 책임

- `Signal` 정의
- 판단 사유와 메타데이터 구조 정의
- `TradeDecision` 정의

## 포함 범위

- `src/domain/signal/signal.py`
- `src/domain/signal/signal_reason.py`
- `src/domain/signal/trade_decision.py`

## 제외 범위

- 전략 조합 규칙
- 포지션 크기 계산
- 주문 실행 세부사항

## 선행 조건

- 없음

## 산출물

- 시그널 방향 표현
- 신뢰도 규칙
- 매매 의사결정 모델

## 완료 기준

- 전략, 리스크, 실행 모듈이 동일한 판단 언어를 사용한다.
- `WAIT` 같은 비진입 상태가 명확히 표현된다.
- 메타데이터가 확장 가능하지만 핵심 필드는 흔들리지 않는다.

## 다음 연결 모듈

- Module D
- Module E
- Module F
- Module G
