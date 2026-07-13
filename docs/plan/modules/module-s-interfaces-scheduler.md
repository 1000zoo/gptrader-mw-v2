# Module S: `src/interfaces/scheduler`

## 목적

유스케이스 실행 시점을 정의하는 스케줄 진입점을 정리한다.

## 책임

- 거래 실행 스케줄러 정의
- 전략 수명주기 스케줄러 정의
- 실행 주기와 호출 대상 연결

## 포함 범위

- `src/interfaces/scheduler/trade_scheduler.py`
- `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`

## 제외 범위

- 시그널 계산
- 백테스트 로직
- 거래소 API 호출

## 선행 조건

- Module K
- Module M

## 산출물

- 스케줄 엔트리 구조
- 유스케이스 호출 연결점
- 운영 주기 구분 기준

## 완료 기준

- 스케줄러가 시간과 호출만 관리한다.
- 판단 로직이 스케줄러에 들어가지 않는다.
- 거래 흐름과 lifecycle 흐름이 분리된 엔트리로 유지된다.

## 다음 연결 모듈

- 운영 배포 설정
