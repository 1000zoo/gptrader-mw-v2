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

| Module | Path                                          | Status        | Depends On           | Next Targets     | Notes           |
|--------|-----------------------------------------------|---------------|----------------------|------------------|-----------------|
| A      | `src/domain/market`                           | `done`        | 없음                   | B, D, K          | 기초 시장 모델 고정 완료  |
| B      | `src/domain/indicator`                        | `done`        | A                    | D, E, L          | 지표 결과 구조 고정 완료  |
| C      | `src/domain/signal`                           | `done`        | 없음                   | D, E, F, G       | 판단 공통 언어 고정 완료  |
| D      | `src/domain/strategy`                         | `done`        | A, B, C              | E, I, L          | 전략 계약 고정 완료     |
| E      | `src/domain/signal_generator`                 | `done`        | C, D                 | I, K, L          | 전략 조합 규칙 고정 완료  |
| F      | `src/domain/risk`                             | `done`        | C                    | K                | 리스크 계산 언어 고정 완료 |
| G      | `src/domain/position`                         | `done`        | C                    | H, T             | 포지션 상태 모델 고정 완료 |
| H      | `src/domain/execution`                        | `done`        | C, G                 | J, N, K          | 주문 공통 계약 고정 완료 |
| I      | `src/domain/lifecycle`                        | `not started` | C, D, E              | J, L, M, O       | 전략 수명주기 모델      |
| J      | `src/domain/ports`                            | `not started` | 관련 도메인 모델            | K, L, M, N, O, P | 어댑터 계약 경계       |
| K      | `src/application/usecases/trade`              | `not started` | A-J 중 거래 관련          | R, S, T          | 실거래 오케스트레이션     |
| L      | `src/application/usecases/research`           | `not started` | B, C, D, E, I, J     | M, O             | 연구 흐름 분리        |
| M      | `src/application/usecases/strategy_lifecycle` | `not started` | I, J, L              | R, S             | 등록-승격 흐름        |
| N      | `src/infrastructure/exchange`                 | `not started` | J, 관련 도메인 모델         | K, T             | 거래소 adapter 분리  |
| O      | `src/infrastructure/persistence`              | `not started` | I, J                 | K, L, M          | 저장소 구현          |
| P      | `src/infrastructure/llm`                      | `not started` | J, LLM 전략 계약         | D, E             | LLM adapter     |
| Q      | `src/infrastructure/messaging`                | `not started` | 알림 포트 확정 시           | M                | 운영 알림 보조        |
| R      | `src/interfaces/api`                          | `not started` | 관련 application 유스케이스 | 운영 연동            | HTTP 진입점        |
| S      | `src/interfaces/scheduler`                    | `not started` | K, M                 | 운영 배포 설정         | 스케줄 엔트리         |
| T      | `src/interfaces/websocket`                    | `not started` | G, K, N              | 운영 모니터링          | 실시간 포지션 이벤트     |

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
