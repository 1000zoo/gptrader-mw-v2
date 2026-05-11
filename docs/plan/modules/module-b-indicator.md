# Module B: `src/domain/indicator`

## 목적

시장 데이터로부터 계산된 지표를 도메인에서 다룰 수 있도록 입력과 출력 모델을 정의한다.

## 책임

- 지표 값 모델 정의
- 지표 집합 구조 정의
- 지표 계산기 경계 정의

## 포함 범위

- `src/domain/indicator/indicator_value.py`
- `src/domain/indicator/indicator_set.py`
- `src/domain/indicator/indicator_calculator.py`

## 제외 범위

- TA 라이브러리 직접 호출
- 거래소별 원본 데이터 보정
- 전략 판단 로직

## 선행 조건

- Module A 완료 또는 계약 확정

## 산출물

- 지표 키 네이밍 규칙
- 단일 캔들 기준 지표 표현
- 타임프레임별 지표 집합 모델

## 완료 기준

- 전략이 특정 벤더 포맷 없이 지표를 읽을 수 있다.
- 지표 계산 결과를 동일한 구조로 전달할 수 있다.
- 후속 전략 모듈이 필요한 필드 구조를 참조할 수 있다.

## 다음 연결 모듈

- Module D
- Module E
- Module L
