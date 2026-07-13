# Module T: `src/interfaces/websocket`

## 목적

거래소 포지션 이벤트를 시스템 유스케이스로 연결하는 실시간 진입점을 정리한다.

## 책임

- 포지션 이벤트 수신 진입점 정의
- 외부 이벤트를 application 입력으로 매핑
- 스트림 어댑터와 유스케이스 연결

## 포함 범위

- `src/interfaces/websocket/position_listener.py`
- `src/interfaces/websocket/event_mapper.py`

## 제외 범위

- 웹소켓 프로토콜 상세 구현
- 도메인 상태 전이 규칙
- DB 저장 구현

## 선행 조건

- Module G
- Module K
- Module N

## 산출물

- 리스너 진입점 구조
- 이벤트 매핑 책임 분리
- 유스케이스 연결 경계

## 완료 기준

- 프로토콜 세부사항은 infrastructure에 남고, 여기서는 진입점만 가진다.
- 포지션 이벤트가 domain/application 언어로 번역된다.
- 포지션 추적 흐름이 스케줄러 흐름과 분리된다.

## 다음 연결 모듈

- 운영 모니터링
