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
| OP-1 | Runtime environment | `ready` | 없음 | Python 3.10+ 명령, 의존성, 테스트 명령이 정리되고 `python -m pytest`가 통과한다. | 현재 `C:\Python310\python.exe -m pytest -q` 통과 이력 있음 |
| OP-2 | Local composition root | `ready` | OP-1 | fake/local adapters로 앱을 시작하고 readiness를 확인할 수 있다. | 다음 최우선 작업 |
| OP-3 | Concrete strategy/indicator path | `queued` | OP-2 | 테스트 fake가 아닌 전략/지표 입력으로 dry-run command를 만들 수 있다. | `src/domain/strategy/implementations` 비어 있음 |
| OP-4 | Local persistence/recovery | `queued` | OP-2 | 현재 포지션, 주문, 실행 리포트, 런 상태를 저장/복구한다. | DDL은 있으나 adapter 부족 |
| OP-5 | API readiness/status | `queued` | OP-2, OP-4 | health/readiness/status가 runtime 의존성 상태를 보여준다. | trade control보다 먼저 |
| OP-6 | Scheduler local runner | `queued` | OP-2, OP-3 | 동일 symbol/timeframe 중복 없이 dry-run trade schedule을 한 번 실행한다. | APScheduler 또는 단순 loop 결정 필요 |
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

### 2026-06-11 Runtime Planning Reset

- Agent: Codex
- Status: module progress -> runtime progress
- Plan: `docs/plans/operations/runtime/latest.md`
- Summary: 기존 Module A-T progress board와 실행 관련 latest 문서를 각 history 폴더에 보존하고, 실제 운영 실행을 위한 OP-1~OP-11 로드맵으로 progress board를 재작성했다.
- Verification: 문서 구조 변경만 수행했다. 다음 구현 작업에서 `C:\Python310\python.exe -m pytest -q`를 실행한다.
- Follow-up: OP-1/OP-2부터 진행해 로컬 composition root와 health/readiness 실행 경로를 만든다.
