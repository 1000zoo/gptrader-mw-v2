# Module R: `src/interfaces/api`

## 목적

유스케이스를 외부 HTTP 요청으로 노출하는 진입점을 정리한다.

## 책임

- 전략 관련 API 진입점 정의
- 거래 관련 API 진입점 정의
- 포지션 관련 API 진입점 정의

## 포함 범위

- `src/interfaces/api/strategy_controller.py`
- `src/interfaces/api/trade_controller.py`
- `src/interfaces/api/position_controller.py`

## 제외 범위

- 비즈니스 규칙
- 거래소 호출
- 저장소 구현

## 선행 조건

- 관련 application 유스케이스

## 산출물

- 요청/응답 매핑 기준
- 컨트롤러 분리 기준
- 오류 응답 변환 경계

## 완료 기준

- 컨트롤러가 유스케이스 호출만 담당한다.
- 입력 검증과 응답 변환 책임이 명확하다.
- 운영 제어 API와 연구용 API가 혼동되지 않는다.

## 다음 연결 모듈

- 외부 운영 환경 연동
