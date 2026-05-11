# Module J: `src/domain/ports`

## 목적

상위 레이어가 필요로 하는 외부 의존성 계약을 명확히 정의한다.

## 책임

- 시장 데이터 조회 포트 정의
- 계좌 조회 포트 정의
- 주문 실행 포트 정의
- 저장소 포트 정의

## 포함 범위

- `src/domain/ports/market_data_port.py`
- `src/domain/ports/account_port.py`
- `src/domain/ports/order_execution_port.py`
- `src/domain/ports/strategy_repository_port.py`
- `src/domain/ports/signal_log_repository_port.py`

## 제외 범위

- 구체 구현
- 의존성 주입 조립
- 인터페이스 레이어 진입점

## 선행 조건

- 관련 도메인 모델 확정

## 산출물

- 포트 인터페이스
- 성공/실패 계약 언어
- 입력/출력 모델 연결 기준

## 완료 기준

- application 레이어가 concrete adapter 없이 설계 가능하다.
- infrastructure 레이어가 구현 대상으로 삼을 명확한 계약이 있다.
- 포트 메서드명이 책임을 정확히 드러낸다.

## 다음 연결 모듈

- Module K
- Module L
- Module M
- Module N
- Module O
- Module P
