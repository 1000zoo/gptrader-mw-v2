# Module N: `src/infrastructure/exchange`

## 목적

거래소별 시장 데이터, 계좌, 주문, 포지션 스트림 어댑터를 구현할 구조를 정리한다.

## 책임

- 시장 데이터 어댑터 구현
- 계좌 조회 어댑터 구현
- 주문 실행 어댑터 구현
- 포지션 스트림 어댑터 구현

## 포함 범위

- `src/infrastructure/exchange/market_data/`
- `src/infrastructure/exchange/account/`
- `src/infrastructure/exchange/order_execution/`
- `src/infrastructure/exchange/position_stream/`

## 제외 범위

- 도메인 모델 정의
- 유스케이스 오케스트레이션
- API 엔드포인트

## 선행 조건

- Module J
- 관련 도메인 모델

## 산출물

- 거래소별 adapter 디렉토리 기준
- 포트 구현 단위 분리 기준
- 벤더 응답 매핑 규칙

## 완료 기준

- 시장 데이터, 계좌, 주문, 스트림 책임이 섞이지 않는다.
- 벤더 SDK 타입이 상위 레이어로 새지 않는다.
- Binance 외 거래소 추가가 구조적으로 가능하다.

## 다음 연결 모듈

- Module K
- Module T
