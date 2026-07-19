# Module H: `src/domain/execution`

## 목적

주문 실행과 체결 결과를 벤더 비의존적인 도메인 모델로 정의한다.

## 책임

- 주문 요청 모델 정의
- 주문 결과 모델 정의
- 실행 리포트 표현 정의

## 포함 범위

- `src/domain/execution/order_request.py`
- `src/domain/execution/order_result.py`
- `src/domain/execution/execution_report.py`

## 제외 범위

- 거래소 SDK 타입
- HTTP 요청 구현
- 재시도 정책

## 선행 조건

- Module C
- Module G

## 산출물

- 주문 요청 필드 구조
- 체결 결과 공통 모델
- 실패 표현 초안

## 완료 기준

- 주문 실행 포트가 이 모델을 기준으로 정의 가능하다.
- 거래소별 결과를 공통 구조로 매핑할 수 있다.
- application 레이어가 벤더 세부사항을 몰라도 된다.

## 다음 연결 모듈

- Module J
- Module N
- Module K
