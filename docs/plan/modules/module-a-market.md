# Module A: `src/domain/market`

## 목적

시장 데이터를 시스템 전체에서 공통으로 이해할 수 있게 기본 도메인 모델을 정의한다.

## 책임

- 캔들, 심볼, 타임프레임, 시장 스냅샷 모델 정의
- OHLCV 표준 필드와 불변조건 정의
- 전략과 유스케이스가 공유할 시장 입력 언어 고정

## 포함 범위

- `src/domain/market/candle.py`
- `src/domain/market/symbol.py`
- `src/domain/market/timeframe.py`
- `src/domain/market/market_snapshot.py`

## 제외 범위

- 거래소 응답 파싱
- DB 저장 형식
- 지표 계산 로직

## 선행 조건

- 없음

## 산출물

- 도메인 값 객체와 엔티티 초안
- 필드 의미와 필수값 규칙
- 테스트 대상이 되는 기본 불변조건

## 완료 기준

- 타임프레임과 심볼 표현이 코드 전반에서 재사용 가능하다.
- 캔들 모델 필드명이 거래소 벤더와 무관하다.
- 다른 모듈이 참조 가능한 안정된 입력 모델이 정리된다.

## 다음 연결 모듈

- Module B
- Module D
- Module K
