# Module F: `src/domain/risk`

## 목적

시그널을 실제 포지션 크기와 진입 가능 여부로 바꾸는 리스크 규칙을 정의한다.

## 책임

- 포지션 사이징 규칙 정의
- 노출 한도와 진입 제한 규칙 정의
- 리스크 정책 객체 정의

## 포함 범위

- `src/domain/risk/position_sizer.py`
- `src/domain/risk/risk_policy.py`
- `src/domain/risk/exposure_limit.py`

## 제외 범위

- 계좌 API 조회
- 주문 전송
- 손익 기록 저장

## 선행 조건

- Module C

## 산출물

- 포지션 크기 계산 입력/출력 구조
- 신뢰도 기반 사이징 규칙
- 리스크 차단 판단 규칙

## 완료 기준

- 계좌 상태를 입력으로 받아 순수 계산만 수행한다.
- 진입 불가 사유가 표현 가능하다.
- `TradeDecision` 생성에 필요한 정보가 정리된다.

## 다음 연결 모듈

- Module K
