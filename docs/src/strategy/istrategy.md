# Strategy Module: IStrategy

## 개요

`IStrategy`는 모든 전략의 공통 부모 인터페이스입니다.
현재 구현은 다음 원칙을 강제합니다.

- 전략은 외부에서 계산된 인디케이터만 입력으로 받음
- 입력은 멀티 타임프레임(`1m`, `5m`, `15m`, `30m`, `1h`) 구조
- 전략 결과는 단일 의사결정 1건 반환
- 허용된 인디케이터 컬럼만 사용 가능

## 구현 위치

- 베이스 클래스: `src/strategy/strategies/IStrategy.py`
- 계약 모델: `src/strategy/strategies/models.py`

## 데이터 계약

### StrategyInitConfig

- `strategy_name: str`
- `symbol: str`
- `timeframes: list["1m" | "5m" | "15m" | "30m" | "1h"]`
- `lookback_by_tf: dict[timeframe, int]`
- `params: dict[str, Any]`

`init_strategy` 시 검증:
- `timeframes`의 모든 항목이 `lookback_by_tf`에 존재해야 함
- lookback 값은 `>= 1`

### StrategyRunInput

- `indicators_by_tf: dict[timeframe, list[dict]]`
- `recent_analyzes: list[dict]` (optional)

`indicators_by_tf`의 각 row(dict)는 `ALLOWED_INDICATOR_COLUMNS` 내 키만 허용됩니다.

허용 컬럼은 현재 인디케이터 모듈(`Indicator.get_all`)과 동일합니다.

- `timestamp`
- `ma_fast`, `ma_slow`, `ema_fast`, `ema_slow`, `ema_gap`, `ema_gap_ratio`
- `rsi`
- `macd_line`, `macd_signal_line`, `macd_hist`
- `bollinger_mid`, `bollinger_upper`, `bollinger_lower`, `bollinger_width`
- `true_range`, `atr`
- `dmi_plus_di`, `dmi_minus_di`, `dmi_adx`
- `stochastic_per_k`, `stochastic_per_d`
- `cci`, `roc`, `momentum`, `obv`, `mfi`, `vwap`
- `donchain_upper`, `donchain_lower`
- `keltner_mid`, `keltner_upper`, `keltner_lower`
- `low_linear_regression_slope`, `low_linear_regression_direction`
- `high_linear_regression_slope`, `high_linear_regression_direction`

### StrategyDecision

- `action: "BUY" | "SELL" | "HOLD"`
- `confidence: float (0.0 ~ 1.0)`
- `reason: str`
- `metadata: dict[str, Any]`

## IStrategy 공통 메서드

### `init_strategy(config)`

전략 실행 전 공통 초기화 및 유효성 검증 수행.

### `run_strategy(data)`

전략 구현체가 오버라이드해야 하는 핵심 메서드.
입력은 `StrategyRunInput`, 반환은 `StrategyDecision`.

### `validate_input(data)`

공통 검증:
- 초기화 여부 확인
- 필수 timeframe 존재 확인
- timeframe별 최소 row(lookback) 충족 확인

### `_latest(data, tf, col)`

특정 timeframe의 최신 컬럼값 조회.
- timeframe row가 없거나
- 컬럼이 존재하지 않으면
`ValueError` 발생.

### `_window(data, tf, n)`

특정 timeframe의 최근 `n`개 row 조회.
- timeframe 누락 시 `ValueError`
- `n < 1` 시 `ValueError`

### `_hold(reason, metadata=None)`

공통 HOLD 의사결정 생성 헬퍼.

### `name()`

초기화 이전: 클래스명 반환  
초기화 이후: `config.strategy_name` 반환

## 테스트

- 모델 검증: `tests/test_strategy_models.py`
- 베이스 동작: `tests/test_strategy_base.py`
- 인디케이터 계약 동기화: `tests/test_strategy_indicator_contract.py`

주요 검증 포인트:
- unknown indicator column reject
- 미초기화 실행 reject
- timeframe 누락 reject
- lookback 부족 reject
- helper 동작 확인
- `ALLOWED_INDICATOR_COLUMNS == Indicator.get_all().keys()` 계약 확인

## 참고

설계 문서:
- `docs/plans/strategy/2026-02-19-istrategy-interface-design.md`

구현 계획:
- `docs/plans/strategy/2026-02-19-istrategy-interface-implementation.md`
