# Module K: `src/application/usecases/trade`

## 목적

실거래 흐름을 오케스트레이션하는 유스케이스를 정의한다.

## 책임

- 시장 데이터 조회부터 주문 실행까지 흐름 연결
- 포지션 종료와 동기화 유스케이스 분리
- 도메인 규칙과 포트 호출 순서 정의

## 포함 범위

- `src/application/usecases/trade/execute_trade_usecase.py`
- `src/application/usecases/trade/close_position_usecase.py`
- `src/application/usecases/trade/sync_position_usecase.py`

## 제외 범위

- 거래소 SDK 호출
- HTTP 엔드포인트 구현
- 스케줄 등록

## 선행 조건

- Module A ~ J 중 거래 관련 계약

## 산출물

- 거래 실행 유스케이스 경계
- 입력 DTO 초안
- 실패 처리 경계

## 완료 기준

- 유스케이스가 concrete implementation을 직접 생성하지 않는다.
- 시장 데이터, 전략, 리스크, 실행이 포트 기반으로 연결된다.
- 인터페이스 레이어가 호출 가능한 진입 유스케이스가 생긴다.

## 다음 연결 모듈

- Module R
- Module S
- Module T
