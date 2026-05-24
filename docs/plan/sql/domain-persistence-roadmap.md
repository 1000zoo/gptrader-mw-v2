# Domain Persistence Roadmap

이 문서는 Module O 1차 범위 이후 DB로 관리해야 할 도메인 객체와 DDL 확장 우선순위를 기록한다.

## 현재 반영 완료

Module O 1차 구현에서 아래 객체는 SQLite adapter와 `sql/ddl` 초안이 있다.

- `StrategyDefinition`
- `SignalGeneratorDefinition`
- `StrategyEvaluation`
- `SignalLogEntry`

## 추가 DB 관리 대상

### Priority 1: 운영 거래 상태

실거래, 드라이런, 포지션 동기화의 복구 가능성을 위해 먼저 영속화한다.

- `Position`
  - 테이블 후보: `positions`
  - 이유: 프로세스 재시작 후 현재 포지션 상태를 복원해야 한다.
  - 주요 키: `position_id`, `symbol`, `side`, `status`
- `PositionEvent`
  - 테이블 후보: `position_events`
  - 이유: 웹소켓/체결 이벤트 기반 상태 전이를 재생하고 감사할 수 있어야 한다.
  - 주요 키: `event_id`, `position_id`, `symbol`, `event_type`, `occurred_dt`
- `OrderRequest`
  - 테이블 후보: `order_requests`
  - 이유: 어떤 의사결정이 어떤 주문 요청으로 이어졌는지 추적해야 한다.
  - 주요 키: `request_id`, `symbol`, `side`, `order_type`, `reduce_only`
- `OrderResult`
  - 테이블 후보: `order_results`
  - 이유: 거래소 주문 응답과 내부 주문 요청을 연결해야 한다.
  - 주요 키: `order_id`, `request_id`, `exchange_order_id`, `status`
- `ExecutionReport`
  - 테이블 후보: `execution_reports`
  - 이유: 부분 체결, 수수료, 평균가, 체결 이벤트를 포지션과 대조해야 한다.
  - 주요 키: `report_id`, `order_id`, `position_id`, `symbol`, `executed_dt`

### Priority 2: 의사결정 입력과 결과

전략 판단과 리서치 재현성을 위해 시장/지표/시그널 입력을 저장한다.

- `MarketSnapshot`
  - 테이블 후보: `market_snapshots`
  - 이유: 전략 실행 시점의 캔들 묶음을 재현해야 한다.
  - 주요 키: `snapshot_id`, `symbol`, `timeframe`, `closed_at`
- `Candle`
  - 테이블 후보: `candles`
  - 이유: 백테스트와 지표 계산의 원천 데이터다.
  - 주요 키: `symbol`, `timeframe`, `open_time`
- `IndicatorValue`
  - 테이블 후보: `indicator_values`
  - 이유: 계산 결과 캐시와 전략 입력 감사에 필요하다.
  - 주요 키: `symbol`, `timeframe`, `indicator_key`, `calculated_at`
- `IndicatorSet`
  - 테이블 후보: `indicator_sets`
  - 이유: 한 캔들 시점의 지표 묶음을 재사용할 수 있어야 한다.
  - 주요 키: `indicator_set_id`, `symbol`, `timeframe`, `calculated_at`
- `Signal`
  - 테이블 후보: `signals`
  - 이유: `SignalLogEntry` payload 안의 핵심 판단을 별도 조회 대상으로 승격할 필요가 있다.
  - 주요 키: `signal_id`, `direction`, `confidence`
- `SignalReason`
  - 테이블 후보: `signal_reasons`
  - 이유: 진입/대기 사유를 코드별로 분석할 수 있어야 한다.
  - 주요 키: `reason_id`, `signal_id`, `code`
- `StrategyResult`
  - 테이블 후보: `strategy_results`
  - 이유: 복합 generator에서 개별 전략 판단을 분리 분석해야 한다.
  - 주요 키: `result_id`, `signal_id`, `strategy_name`
- `GeneratedSignal`
  - 테이블 후보: `generated_signals`
  - 이유: 최종 시그널과 전략별 결과의 상위 집계 단위다.
  - 주요 키: `generated_signal_id`, `generator_id`, `signal_id`

### Priority 3: 설정성 도메인 값

운영 중 정책 변경 이력을 관리해야 할 때 영속화한다.

- `ExposureLimit`
  - 테이블 후보: `exposure_limits`
  - 이유: 계좌/심볼별 노출 한도 정책 변경 이력을 보존해야 한다.
  - 주요 키: `limit_id`, `scope`, `symbol`
- `RiskPolicy`
  - 테이블 후보: `risk_policies`
  - 이유: 거래 차단/허용 정책을 실행 결과와 함께 추적해야 한다.
  - 주요 키: `policy_id`, `version`
- `PositionSizer` configuration
  - 테이블 후보: `position_sizer_configs`
  - 이유: 사이징 파라미터가 주문 수량에 미친 영향을 감사해야 한다.
  - 주요 키: `config_id`, `version`
- `PromotionPolicy`
  - 테이블 후보: `promotion_policies`
  - 이유: 전략 승격 기준 변경과 평가 결과를 연결해야 한다.
  - 주요 키: `policy_id`, `version`

## 제외 후보

아래 값 객체는 독립 테이블보다 상위 테이블 컬럼 또는 payload로 보관하는 편이 낫다.

- `Symbol`: 여러 테이블의 `symbol` 컬럼으로 보관한다.
- `Timeframe`: 여러 테이블의 `timeframe` 컬럼으로 보관한다.
- `TradeDecision`: 2026-05-25 전체 테이블 스펙 정리에서 `trade_decisions`로 승격했다. 주문 요청 감사 경로에서 직접 조회가 필요하기 때문이다.

## DDL 작성 기준

- 모든 테이블은 `reg_ymd`, `reg_dt`, `upd_dt`, `use_yn`을 포함한다.
- `use_yn`은 `Y`, `N`만 허용한다.
- 이벤트성 테이블은 append-only를 기본으로 하고, 상태성 테이블은 최신 상태 row와 event log를 분리한다.
- 인덱스에는 가능한 한 `reg_ymd`를 포함한다.
- 운영 조회에 필요한 `symbol`, `timeframe`, `status`, `generator_id`, `strategy_id`, `position_id`, `order_id`는 명시 인덱스 후보로 검토한다.
- JSON payload는 초기 구현 속도를 위해 허용하되, 자주 조회되는 필드는 별도 컬럼으로 승격한다.

## 다음 작업 제안

1. `positions`, `position_events`, `order_requests`, `order_results`, `execution_reports` DDL을 먼저 추가한다.
2. `StrategyRepositoryPort`처럼 position/execution repository port가 필요한지 Module J 후속으로 검토한다.
3. 운영 복구 흐름이 정해진 뒤 `src/infrastructure/persistence/repositories`에 position/execution adapter를 추가한다.

## 전체 테이블 인벤토리

2026-05-25 기준 현재 소스코드의 도메인 모델, 포트, application usecase 흐름을 검토해 필요한 테이블 스펙을 `docs/plan/sql/<domain>/<table>.md`에 분리했다.

상태 의미:

- `not started`: 테이블 필요성은 식별됐지만 세부 계획서가 없다.
- `ready`: `docs/plan/sql` 세부 스펙 문서가 있어 DDL 작성에 착수할 수 있다.
- `done`: 세부 스펙과 현재 SQL DDL 또는 SQLite adapter 구현이 있다.

| Domain | Table | Spec | Status | Source |
|--------|-------|------|--------|--------|
| account | `account_snapshots` | `docs/plan/sql/account/account_snapshots.md` | `ready` | `AccountSnapshot` |
| account | `asset_balances` | `docs/plan/sql/account/asset_balances.md` | `ready` | `AssetBalance` |
| application | `research_runs` | `docs/plan/sql/application/research_runs.md` | `ready` | research usecases |
| application | `strategy_lifecycle_runs` | `docs/plan/sql/application/strategy_lifecycle_runs.md` | `ready` | strategy lifecycle usecases |
| application | `trade_runs` | `docs/plan/sql/application/trade_runs.md` | `ready` | trade usecases |
| execution | `execution_reports` | `docs/plan/sql/execution/execution_reports.md` | `ready` | `ExecutionReport` |
| execution | `order_requests` | `docs/plan/sql/execution/order_requests.md` | `ready` | `OrderRequest` |
| execution | `order_results` | `docs/plan/sql/execution/order_results.md` | `ready` | `OrderResult` |
| indicator | `indicator_sets` | `docs/plan/sql/indicator/indicator_sets.md` | `ready` | `IndicatorSet` |
| indicator | `indicator_values` | `docs/plan/sql/indicator/indicator_values.md` | `ready` | `IndicatorValue` |
| lifecycle | `promotion_policies` | `docs/plan/sql/lifecycle/promotion_policies.md` | `ready` | `PromotionPolicy` |
| lifecycle | `strategy_evaluation_metrics` | `docs/plan/sql/lifecycle/strategy_evaluation_metrics.md` | `ready` | `StrategyEvaluation.metrics` |
| lifecycle | `strategy_evaluations` | `docs/plan/sql/lifecycle/strategy_evaluations.md` | `done` | `StrategyEvaluation`, current DDL/adapter |
| market | `candles` | `docs/plan/sql/market/candles.md` | `ready` | `Candle` |
| market | `market_snapshot_candles` | `docs/plan/sql/market/market_snapshot_candles.md` | `ready` | `MarketSnapshot.candles` |
| market | `market_snapshots` | `docs/plan/sql/market/market_snapshots.md` | `ready` | `MarketSnapshot` |
| position | `position_events` | `docs/plan/sql/position/position_events.md` | `ready` | `PositionEvent` |
| position | `positions` | `docs/plan/sql/position/positions.md` | `ready` | `Position` |
| risk | `exposure_limits` | `docs/plan/sql/risk/exposure_limits.md` | `ready` | `ExposureLimit` |
| risk | `position_sizer_configs` | `docs/plan/sql/risk/position_sizer_configs.md` | `ready` | `PositionSizer` config |
| risk | `position_sizes` | `docs/plan/sql/risk/position_sizes.md` | `ready` | `PositionSize` |
| risk | `risk_checks` | `docs/plan/sql/risk/risk_checks.md` | `ready` | `RiskCheck` |
| risk | `risk_policies` | `docs/plan/sql/risk/risk_policies.md` | `ready` | `RiskPolicy` |
| signal | `signal_logs` | `docs/plan/sql/signal/signal_logs.md` | `done` | `SignalLogEntry`, current DDL/adapter |
| signal | `signal_reasons` | `docs/plan/sql/signal/signal_reasons.md` | `ready` | `SignalReason` |
| signal | `signals` | `docs/plan/sql/signal/signals.md` | `ready` | `Signal` |
| signal | `trade_decisions` | `docs/plan/sql/signal/trade_decisions.md` | `ready` | `TradeDecision` |
| signal_generator | `generated_signals` | `docs/plan/sql/signal_generator/generated_signals.md` | `ready` | `GeneratedSignal` |
| signal_generator | `signal_generator_definitions` | `docs/plan/sql/signal_generator/signal_generator_definitions.md` | `done` | `SignalGeneratorDefinition`, current DDL/adapter |
| signal_generator | `signal_generator_regime_routes` | `docs/plan/sql/signal_generator/signal_generator_regime_routes.md` | `ready` | `regime_routes` |
| signal_generator | `signal_generator_strategy_links` | `docs/plan/sql/signal_generator/signal_generator_strategy_links.md` | `ready` | `strategy_ids` |
| strategy | `strategy_definitions` | `docs/plan/sql/strategy/strategy_definitions.md` | `done` | `StrategyDefinition`, current DDL/adapter |
| strategy | `strategy_results` | `docs/plan/sql/strategy/strategy_results.md` | `ready` | `StrategyResult` |

## 현재 단계

- 전체 테이블 후보 식별: `done`
- 도메인별 세부 스펙 문서 작성: `done`
- DDL 구현: `not started` for `ready` 테이블, `done` for 기존 Module O 테이블
- Repository port 검토: `not started`
- Persistence adapter 구현: `not started`

다음 단계는 위 인벤토리에서 Priority 1 운영 거래 상태 테이블인 `positions`, `position_events`, `order_requests`, `order_results`, `execution_reports`의 실제 DDL, 인덱스, 제약조건, SQL schema check를 작성하는 것이다.
