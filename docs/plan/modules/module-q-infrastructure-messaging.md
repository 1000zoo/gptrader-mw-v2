# Module Q: `src/infrastructure/messaging`

## 목적

운영 알림을 외부 메신저로 전달하는 보조 인프라 구조를 정리한다.

## 책임

- Slack notifier 구조 정의
- Telegram notifier 구조 정의
- 운영 이벤트 메시지 포맷 경계 정의

## 포함 범위

- `src/infrastructure/messaging/slack_notifier.py`
- `src/infrastructure/messaging/telegram_notifier.py`

## 제외 범위

- 핵심 거래 로직
- 수명주기 유스케이스
- 알림 정책 자체

## 선행 조건

- 알림 포트가 필요한 경우 해당 계약 확정

## 산출물

- notifier adapter 기준
- 운영 메시지 구조 초안
- 실패 격리 기준

## 완료 기준

- 메신저 변경이 상위 레이어에 영향을 주지 않는다.
- 알림 실패가 핵심 거래 흐름을 깨지 않는다.
- 운영 알림 책임이 다른 인프라와 섞이지 않는다.

## 다음 연결 모듈

- Module M
