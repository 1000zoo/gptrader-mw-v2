# Module G: `src/domain/position`

## 목적

현재 포지션 상태와 포지션 이벤트의 도메인 의미를 정의한다.

## 책임

- 포지션 엔티티 정의
- 포지션 상태 전이 규칙 정의
- 웹소켓 또는 체결 이벤트의 도메인 표현 정의

## 포함 범위

- `src/domain/position/position.py`
- `src/domain/position/position_event.py`
- `src/domain/position/position_status.py`

## 제외 범위

- 거래소 웹소켓 클라이언트
- 포지션 조회 API
- DB 영속화

## 선행 조건

- Module C

## 산출물

- 포지션 상태 모델
- 이벤트 종류 정리
- 상태 전이 규칙 초안

## 완료 기준

- 포지션 생성, 유지, 종료 상태가 명확하다.
- 이벤트 기반 갱신 로직이 도메인 언어로 표현된다.
- execution 및 websocket 모듈이 참조할 수 있다.

## 다음 연결 모듈

- Module H
- Module T
