# Gptrader V3 Runtime Progress Board

이 문서는 이제 모듈 구현 현황이 아니라 실제 실행 준비 상태를 추적한다.
이전 Module A-T 중심 progress board는 `docs/history/progress/2026-06-11-module-progress-board.md`에 보존했다.

## 상태 규칙

- `queued`: 해야 할 일이 식별됐지만 아직 착수하지 않음
- `ready`: 선행 조건이 충족되어 바로 시작 가능
- `in progress`: 현재 작업 중
- `blocked`: 선행 조건, 환경, 권한, 외부 계정 문제로 진행 불가
- `done`: 현재 단계 완료

## 운영 원칙

- 실제 실행은 `local` -> `dry-run` -> `testnet` -> `live-armed` 순서로만 전진한다.
- live 주문 경로는 별도 arming flag 없이는 열지 않는다.
- 모든 runtime 작업은 `docs/plans/operations/runtime/latest.md`를 기준으로 진행한다.
- 작업 완료 시 이 파일의 상태와 작업 로그를 함께 갱신한다.

## 현재 목표

가장 가까운 목표는 **로컬에서 안전하게 시작되는 runtime skeleton**이다.
첫 완료 조건은 API health/readiness가 뜨고, fake/local adapter 기반 composition root가 구성되며, 전체 테스트가 통과하는 것이다.

## 실행 준비 현황

| Step | Area | Status | Depends On | Exit Criteria | Notes |
|------|------|--------|------------|---------------|-------|
| OP-1 | Runtime environment | `done` | 없음 | Python 3.10+ 명령, 의존성, 테스트 명령이 정리되고 `python -m pytest`가 통과한다. | `docs/runbooks/local-runtime.md` 추가 |
| OP-2 | Local composition root | `done` | OP-1 | fake/local adapters로 앱을 시작하고 readiness를 확인할 수 있다. | `src/runtime` local skeleton 추가 |
| OP-3 | Concrete strategy/indicator path | `done` | OP-2 | 테스트 fake가 아닌 전략/지표 입력으로 dry-run command를 만들 수 있다. | 예시 moving-average strategy와 local indicator builder 추가 |
| OP-4 | Local persistence/recovery | `done` | OP-2 | 현재 포지션, 주문, 실행 리포트, 런 상태를 저장/복구한다. | SQLite runtime state repository 추가 |
| OP-5 | API readiness/status | `done` | OP-2, OP-4 | health/readiness/status가 runtime 의존성 상태를 보여준다. | `/health`, `/readiness`, `/status` local runtime 연결 |
| OP-6 | Scheduler local runner | `ready` | OP-2, OP-3 | 동일 symbol/timeframe 중복 없이 dry-run trade schedule을 한 번 실행한다. | 다음 최우선 작업 |
| OP-7 | Websocket local runner | `queued` | OP-2, OP-4 | replay/fake stream 이벤트가 `PositionListener`를 통해 저장된다. | Binance 연결 전 로컬 재생 먼저 |
| OP-8 | Messaging wiring | `queued` | OP-2 | runtime failure alert가 caller를 깨지 않고 전송/실패 기록된다. | Slack/Telegram adapter 경계 있음 |
| OP-9 | Binance testnet preflight | `blocked` | OP-2, OP-4, OP-5 | testnet credentials, 권한, futures mode, symbol filter, balance를 점검한다. | 외부 계정/키 필요 |
| OP-10 | Binance testnet rehearsal | `blocked` | OP-9 | submit/close/sync/user stream/reconnect/keepalive/shutdown rehearsal 완료. | live 전 필수 |
| OP-11 | Live readiness review | `blocked` | OP-10 | testnet 증거, 복구, 관측, arming control 확인 완료. | live 주문 전 최종 게이트 |

## 작업 로그 템플릿

```markdown
### YYYY-MM-DD OP-X

- Agent: 담당 세션 또는 이름
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: 무엇을 했는지
- Verification: 실행한 검증 명령
- Follow-up: 다음 작업자가 이어서 할 일
```

## 작업 로그

### 2026-06-12 OP-1

- Agent: Codex
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: `.env.example`에 `GPTRADER_*` local runtime 설정을 추가하고, `docs/runbooks/local-runtime.md`에 Python 3.10, 전체 테스트, import smoke check, local API server 명령을 정리했다.
- Verification: `C:\Python310\python.exe -m pytest -q` -> `210 passed`
- Follow-up: OP-2 local composition root를 기준으로 API readiness/status를 확장한다.

### 2026-06-12 OP-2

- Agent: Codex
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: `src/runtime`에 `RuntimeSettings`, `RuntimeStatus`, `LocalRuntime`, `create_local_app()`을 추가해 external exchange 없이 FastAPI health/readiness 앱을 만들 수 있게 했다. API app에는 `/readiness` endpoint를 추가했다.
- Verification: `C:\Python310\python.exe -c "from src.runtime import create_local_app; app = create_local_app(); print(app.title)"` -> `Gptrader API`; `C:\Python310\python.exe -m pytest -q` -> `210 passed`
- Follow-up: OP-3에서 latest-close-vs-moving-average 같은 deterministic 예시 strategy와 local indicator fixture/loader를 추가한다.

### 2026-06-12 OP-3

- Agent: Codex
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: `LatestCloseMovingAverageStrategy` 예시 구현체와 `src/runtime/local_data.py` local market/indicator/context builder를 추가했다. local readiness는 예시 strategy 평가 방향을 포함해 runtime smoke path가 실제 도메인 `StrategyResult`까지 도달하는지 보여준다.
- Verification: `C:\Python310\python.exe -m pytest tests\domain\strategy\test_moving_average_strategy.py tests\runtime -q` -> `7 passed`; `C:\Python310\python.exe -m pytest -q` -> `213 passed`
- Follow-up: OP-4에서 현재 포지션, 주문/실행 상태, scheduler/stream update를 저장하고 복구하는 local persistence 경계를 만든다.

### 2026-06-12 OP-4

- Agent: Codex
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: `SqliteRuntimeStateRepository`를 추가해 current position, position events, scheduler/stream/order용 generic runtime record payload를 SQLite에 저장하고 복구할 수 있게 했다.
- Verification: `C:\Python310\python.exe -m pytest tests\infrastructure\persistence\test_sqlite_runtime_state_repository.py -q` -> `3 passed`; `C:\Python310\python.exe -m pytest -q` -> `216 passed`
- Follow-up: OP-5에서 runtime status/readiness endpoint가 local persistence 상태와 strategy smoke 상태를 드러내도록 확장한다.

### 2026-06-12 OP-5

- Agent: Codex
- Status: `ready` -> `done`
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: API app에 `/status` endpoint를 추가하고 `LocalRuntime`이 health/readiness/status details를 제공하도록 확장했다. local status는 trade controls와 live order path가 disabled임을 명시한다.
- Verification: `C:\Python310\python.exe -m pytest tests\interfaces\api tests\runtime -q` -> `13 passed`; `C:\Python310\python.exe -m pytest -q` -> `217 passed`
- Follow-up: OP-6에서 중복 실행을 막는 local scheduler runner와 dry-run command 실행 기록을 추가한다.

### 2026-06-11 Runtime Planning Reset

- Agent: Codex
- Status: module progress -> runtime progress
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: 기존 Module A-T progress board와 실행 관련 latest 문서를 각 history 폴더에 보존하고, 실제 운영 실행을 위한 OP-1~OP-11 로드맵으로 progress board를 재작성했다.
- Verification: 문서 구조 변경만 수행했다. 다음 구현 작업에서 `C:\Python310\python.exe -m pytest -q`를 실행한다.
- Follow-up: OP-1/OP-2부터 진행해 로컬 composition root와 health/readiness 실행 경로를 만든다.
