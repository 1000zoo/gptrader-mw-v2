# Module L: `src/application/usecases/research`

## 목적

백테스트, 드라이런, 평가 흐름을 실거래 흐름과 분리해 정의한다.

## 책임

- 백테스트 유스케이스 정의
- 드라이런 유스케이스 정의
- 평가 결과 생성 흐름 정의

## 포함 범위

- `src/application/usecases/research/backtest_strategy_usecase.py`
- `src/application/usecases/research/dry_run_strategy_usecase.py`
- `src/application/usecases/research/evaluate_strategy_usecase.py`

## 제외 범위

- 실거래 주문 실행
- 스케줄러 구성
- 전략 승격 정책 자체

## 선행 조건

- Module B
- Module C
- Module D
- Module E
- Module I
- Module J

## 산출물

- 연구용 실행 흐름
- 평가 결과 전달 구조
- lifecycle로 넘길 결과 경계

## 완료 기준

- 실거래 유스케이스와 연구 유스케이스가 섞이지 않는다.
- 평가 결과가 lifecycle 모델로 전달 가능하다.
- persistence 포트 없이도 경계가 문서상 명확하다.

## 다음 연결 모듈

- Module M
- Module O
