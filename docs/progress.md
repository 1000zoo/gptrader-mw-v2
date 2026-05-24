# Gptrader V3 Progress Board

이 문서는 에이전트 작업 현황을 전체적으로 추적하는 보드다.
모든 에이전트는 작업 시작 전 이 파일을 읽고, 작업 종료 후 상태를 갱신해야 한다.

## 상태 규칙

- `not started`: 아직 시작하지 않음
- `ready`: 선행 의존성이 충족되어 다음 에이전트가 시작 가능
- `in progress`: 누군가 작업 중
- `blocked`: 선행 조건 또는 계약 문제로 진행 불가
- `done`: 현재 단계 작업 완료

## 에이전트 작업 규칙

- 작업 시작 전 담당 모듈을 `in progress`로 바꾼다.
- 작업 중 범위가 바뀌면 관련 모듈 상태와 메모를 같이 갱신한다.
- 작업 완료 후 `done`으로 바꾸고, 다음 후보 모듈을 확인한다.
- 선행 모듈이 미완료인데 구현이 필요하면 `blocked`로 남기고 이유를 적는다.
- 상세 지침은 `docs/plan/modules/*.md`를 따른다.

## 현재 우선순위

1. Module A
2. Module C
3. Module G
4. Module B
5. Module D
6. Module F
7. Module H
8. Module E
9. Module I
10. Module J

## 전체 현황

| Module | Path                                          | Status        | Depends On           | Next Targets     | Notes            |
|--------|-----------------------------------------------|---------------|----------------------|------------------|------------------|
| A      | `src/domain/market`                           | `done`        | 없음                   | B, D, K          | 기초 시장 모델 고정 완료   |
| B      | `src/domain/indicator`                        | `done`        | A                    | D, E, L          | 지표 결과 구조 고정 완료   |
| C      | `src/domain/signal`                           | `done`        | 없음                   | D, E, F, G       | 판단 공통 언어 고정 완료   |
| D      | `src/domain/strategy`                         | `done`        | A, B, C              | E, I, L          | 전략 계약 고정 완료      |
| E      | `src/domain/signal_generator`                 | `done`        | C, D                 | I, K, L          | 전략 조합 규칙 고정 완료   |
| F      | `src/domain/risk`                             | `done`        | C                    | K                | 리스크 계산 언어 고정 완료  |
| G      | `src/domain/position`                         | `done`        | C                    | H, T             | 포지션 상태 모델 고정 완료  |
| H      | `src/domain/execution`                        | `done`        | C, G                 | J, N, K          | 주문 공통 계약 고정 완료   |
| I      | `src/domain/lifecycle`                        | `done`        | C, D, E              | J, L, M, O       | 전략 수명주기 모델 고정 완료 |
| J      | `src/domain/ports`                            | `done`        | 관련 도메인 모델            | K, L, M, N, O, P | 어댑터 계약 경계 고정 완료 |
| K      | `src/application/usecases/trade`              | `done`        | A-J 중 거래 관련          | R, S, T          | 거래 유스케이스 1차 완료   |
| L      | `src/application/usecases/research`           | `done`        | B, C, D, E, I, J     | M, O             | 연구 흐름 분리 완료      |
| M      | `src/application/usecases/strategy_lifecycle` | `done`        | I, J, L              | R, S             | 등록-승격 흐름 완료      |
| N      | `src/infrastructure/exchange`                 | `done`        | J, 관련 도메인 모델         | K, T             | 1차 adapter 경계 완료, 실 Binance 연동 후속 필요 |
| O      | `src/infrastructure/persistence`              | `done`        | I, J                 | K, L, M          | 저장소 구현 완료        |
| P      | `src/infrastructure/llm`                      | `done`        | J, LLM 전략 계약         | D, E             | LLM adapter      |
| Q      | `src/infrastructure/messaging`                | `not started` | 알림 포트 확정 시           | M                | 운영 알림 보조         |
| R      | `src/interfaces/api`                          | `not started` | 관련 application 유스케이스 | 운영 연동            | HTTP 진입점         |
| S      | `src/interfaces/scheduler`                    | `not started` | K, M                 | 운영 배포 설정         | 스케줄 엔트리          |
| T      | `src/interfaces/websocket`                    | `not started` | G, K, N              | 운영 모니터링          | 실시간 포지션 이벤트      |

## 후속 작업

| Item | Path | Status | Depends On | Notes |
|------|------|--------|------------|-------|
| SQL-DOMAIN-PERSISTENCE | `docs/plan/sql/domain-persistence-roadmap.md` | `ready` | Module O | 추가 도메인 객체 DDL 확장 필요. 우선순위는 포지션/주문/체결, 시장/지표/시그널 입력, 리스크/승격 정책 순서로 기록됨. |

## 작업 로그 템플릿

아래 형식으로 상태를 갱신한다.

```markdown
### YYYY-MM-DD Module X

- Agent: 담당 세션 또는 이름
- Status: `in progress` -> `done`
- Summary: 무엇을 했는지
- Follow-up: 다음 에이전트가 이어서 할 일
```

## 작업 로그

### 2026-05-24 Module P

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-p-infrastructure-llm.md`
- Design: `docs/plans/2026-05-24-module-p-infrastructure-llm-design.md`
- Summary: `src/infrastructure/llm`에 vendor-neutral LLM 경계를 추가했다. `PromptBuilder`는 `StrategyContext`를 deterministic prompt payload로 조립하고, `LLMClient`는 주입된 low-level client를 호출하며 SDK/transport 실패를 `LLMClientError`로 번역한다. `ResponseParser`는 strict JSON 응답을 기존 `StrategyResult`, `Signal`, `SignalReason`으로 변환하고 파싱 실패를 `LLMResponseParseError`로 번역한다.
- Follow-up: 다음 에이전트는 Module D/E 후속에서 LLM 기반 전략 구현체 또는 signal generator 연결을 추가할 수 있다. 실제 벤더 SDK 생성, 모델 설정, retry/backoff 정책은 composition root 또는 별도 infrastructure 설정 작업에서 진행한다.

### 2026-05-24 Module O

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-o-infrastructure-persistence.md`
- Design: `docs/plans/2026-05-24-module-o-infrastructure-persistence-design.md`
- Summary: `src/infrastructure/persistence`에 SQLite 기반 `StrategyRepositoryPort`, `SignalLogRepositoryPort` adapter를 추가하고 lifecycle 정의, generator 정의, 평가 결과, generated signal log가 도메인 객체로 round-trip 되도록 테스트로 고정했다. `sql/ddl`, `sql/tests`, `sql/plans`, `sql/seeds`에 persistence 테이블/인덱스/제약조건/checklist 기준도 추가했다.
- Follow-up: 추가 도메인 객체 DDL 확장은 `docs/plan/sql/domain-persistence-roadmap.md` 기준으로 나중에 진행한다. 다음 에이전트는 Module P에서 LLM adapter를 진행하거나, Module R/S/T에서 application usecase를 API, scheduler, websocket 진입점으로 연결할 수 있다. 운영 DB 전환 시 PostgreSQL migration은 `src/infrastructure/persistence/migrations`와 `sql/ddl` 기준을 사용한다.

### 2026-05-24 Module N

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-n-infrastructure-exchange.md`
- Summary: `src/infrastructure/exchange/binance` 아래에 시장 데이터, 계좌, 주문 실행, 포지션 스트림 책임별 패키지를 만들고 Binance용 mapper/adapter 1차 구조를 추가했다. adapter는 주입된 client를 통해 포트 계약을 구현하고, raw Binance payload를 도메인 `Candle`, `MarketSnapshot`, `AccountSnapshot`, `OrderResult`로 변환하도록 테스트로 고정했다. 이후 Upbit 등 다른 거래소는 `src/infrastructure/exchange/upbit` 같은 형제 디렉토리로 추가한다.
- Follow-up: 실제 Binance REST/futures client 생성, 인증 설정, retry/timeout/rate-limit/error translation, `load_execution_reports` 구현, authenticated position/user-data stream runtime은 다음 Module N 후속 작업 또는 Module T 연결 작업에서 진행해야 한다. 이 후속 범위는 `docs/plans/2026-05-24-module-n-infrastructure-exchange.md`와 `src/infrastructure/exchange/binance/position_stream/README.md`에도 기록되어 있다.

### 2026-05-24 Module M

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-m-application-strategy-lifecycle.md`
- Design: `docs/plans/2026-05-24-module-m-application-strategy-lifecycle-design.md`
- Summary: `src/application/usecases/strategy_lifecycle`에 `RegisterStrategyUseCase`, `PromoteStrategyUseCase`, `RunStrategyLifecycleUseCase`와 관련 command/result DTO를 추가했다. 전략/시그널 생성기 정의 등록, 평가 기반 승격 판단, 최신 또는 명시 평가 승격 실행 흐름을 `StrategyRepositoryPort`와 `PromotionPolicy` 경계로 고정했다.
- Follow-up: 다음 에이전트는 Module O에서 lifecycle persistence adapter를 구현하거나, Module R/S에서 strategy lifecycle 유스케이스를 API와 스케줄러 진입점에 연결할 수 있다.

### 2026-05-24 Module L

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-l-application-research.md`
- Design: `docs/plans/2026-05-24-module-l-application-research-design.md`
- Summary: `src/application/usecases/research`에 `BacktestStrategyUseCase`, `DryRunStrategyUseCase`, `EvaluateStrategyUseCase`와 연구용 command/result DTO를 추가했다. 연구 흐름은 시장 스냅샷 조회, 전략/시그널 생성기 실행, lifecycle 평가 생성까지만 담당하고 실거래 주문 실행과 persistence 포트는 사용하지 않도록 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module M에서 전략 등록-평가-승격 흐름을 application 경계로 묶거나, Module O에서 lifecycle/research 결과 저장소 구현을 진행할 수 있다.

### 2026-05-24 Module K

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-k-application-trade.md`
- Summary: `src/application/usecases/trade`에 `ExecuteTradeUseCase`, `ClosePositionUseCase`, `SyncPositionUseCase`와 관련 command/result DTO를 추가했다. 시장 스냅샷 조회, 전략 컨텍스트 생성, 시그널 생성/로그 기록, 포지션 사이징, 리스크 검증, 시장가 진입 주문, reduce-only 청산 주문, 체결 리포트 기반 포지션 동기화 흐름을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module R/S/T에서 거래 유스케이스 호출 경계를 연결하거나, Module N의 거래소 어댑터에서 `OrderExecutionPort`와 `MarketDataPort` 구현을 진행할 수 있다.

### 2026-05-24 Module J

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-j-ports.md`
- Summary: `src/domain/ports`에 시장 데이터, 계좌, 주문 실행, 전략 저장소, 시그널 로그 저장소 포트 계약을 추가하고, 계좌 잔고 및 시그널 로그 항목의 기본 불변조건을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module K/L/M에서 이 포트 계약으로 application 유스케이스를 설계하거나, Module N/O에서 exchange/persistence adapter 구현을 진행할 수 있다.

### 2026-05-24 Module I

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-i-lifecycle.md`
- Summary: `src/domain/lifecycle`에 `StrategyDefinition`, `SignalGeneratorDefinition`, `StrategyEvaluation`, `PromotionPolicy`를 추가하고, 전략 정의/조합 정의/평가 지표/승격 가능 여부 판단 규칙을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module J에서 lifecycle 저장 및 오케스트레이션에 필요한 포트 계약을 정의하거나, Module L/M/O에서 이 lifecycle 모델을 사용할 수 있다.

### 2026-05-24 Module H

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-h-execution.md`
- Summary: `src/domain/execution`에 `OrderRequest`, `OrderResult`, `ExecutionReport`를 추가하고, 주문 요청 검증, 주문 결과 상태 표현, 체결 리포트의 포지션 이벤트 변환 규칙을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module I의 전략 수명주기 모델을 진행하거나, Module J에서 실행 포트를 Module H 계약에 연결할 수 있다.

### 2026-05-24 Module E

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-e-signal-generator.md`
- Summary: `src/domain/signal_generator`에 `GeneratedSignal`, `SignalGenerator`, `CompositeSignalGenerator`, `RegimeSignalGenerator`를 추가하고, 전략 결과 조합 및 레짐 기반 위임 규칙을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module H의 주문/실행 계약을 진행하거나, Module I의 전략 수명주기 모델을 Module D/E 계약에 연결할 수 있다.

### 2026-05-24 Module F

- Agent: Codex
- Status: `in progress` -> `done`
- Plan: `docs/plans/2026-05-24-module-f-risk.md`
- Summary: `src/domain/risk`에 `ExposureLimit`, `RiskPolicy`, `PositionSizer` 계약을 추가하고, 계좌 입력 기반 노출 한도, 진입 차단 사유, 신뢰도 기반 포지션 사이징 규칙을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module H의 주문/실행 계약을 진행하거나, Module E의 전략 결과 조합 규칙을 정의할 수 있다.

### 2026-05-24 Plan Document Enforcement

- Agent: Codex
- Status: `done`
- Plan: `docs/codex.md`
- Summary: 모든 에이전트가 구현 전 `docs/plans` 계획 문서를 작성하거나 갱신하도록 `docs/codex.md`와 `docs/plan/modules/README.md`에 하드 게이트를 추가했다. 계획 문서가 없으면 구현 시작, 완료 처리, `done` 상태 변경을 금지한다.
- Follow-up: 다음 에이전트는 모듈 작업 시작 전과 종료 전 담당 모듈의 `docs/plans` 문서 존재 여부와 최신성을 반드시 확인한다.

### 2026-05-24 Module D

- Agent: Codex
- Status: `in progress` -> `done`
- Summary: `src/domain/strategy`에 `StrategyContext`, `StrategyResult`, `Strategy` 프로토콜과 구현 확장 디렉토리 기준을 추가하고, 시장/지표 입력 정합성 및 전략 결과 계약을 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module F의 리스크 계산 언어, Module H의 주문/실행 계약, 또는 Module E의 전략 결과 조합 규칙을 진행할 수 있다.

### 2026-05-24 Module B

- Agent: Codex
- Status: `in progress` -> `done`
- Summary: `src/domain/indicator`에 `IndicatorValue`, `IndicatorSet`, `IndicatorCalculator` 계약을 추가하고, 지표 키 정규화, 단일 캔들 시점의 지표 집합, 계산기 포트 경계를 테스트로 고정했다.
- Follow-up: 다음 에이전트는 Module D의 전략 계약을 진행하거나, Module F의 리스크 계산 언어 또는 Module H의 주문/실행 계약을 정의할 수 있다.

### 2026-05-24 Module G

- Agent: Codex
- Status: `in progress` -> `done`
- Summary: `src/domain/position`에 `PositionStatus`, `PositionEvent`, `Position` 도메인 모델과 이벤트 기반 포지션 증가, 감소, 종료 규칙을 추가했다.
- Follow-up: 다음 에이전트는 Module B 또는 Module D를 진행하거나, Module G를 선행 조건으로 삼아 Module H의 주문/실행 계약 또는 Module T의 웹소켓 이벤트 반영 경계를 정의한다.

### 2026-05-12 Module C

- Agent: Codex
- Status: `in progress` -> `done`
- Summary: `src/domain/signal`에 `Signal`, `SignalReason`, `TradeDecision` 도메인 모델과 판단 방향/최종 행동 enum, 신뢰도 및 진입 방향 검증 테스트를 추가했다.
- Follow-up: 다음 에이전트는 Module G를 진행하거나, Module C를 선행 조건으로 삼아 Module F의 리스크 계산 언어 또는 Module D의 전략 계약을 정의한다.

### 2026-05-12 Module A

- Agent: Codex
- Status: `in progress` -> `done`
- Summary: `src/domain/market`에 `Symbol`, `Timeframe`, `Candle`, `MarketSnapshot` 도메인 모델과 기본 불변조건 테스트를 추가했다.
- Follow-up: 다음 에이전트는 Module C 또는 Module G를 진행하거나, Module A를 선행 조건으로 삼아 Module B의 지표 입력 계약을 정의한다.

### 2026-05-12 Planning Setup

- Agent: Codex
- Status: `done`
- Summary: 모듈별 상세 plan 문서와 전체 progress 보드를 생성했다.
- Follow-up: 다음 에이전트는 Module A, C, G 중 하나를 선택해 계약과 디렉토리 초안을 시작한다.
