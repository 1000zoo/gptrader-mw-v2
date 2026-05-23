# Module Plans

이 디렉토리는 에이전트가 모듈 단위로 작업할 때 읽어야 하는 상세 계획 문서를 모아둔 곳이다.

## 사용 규칙

- 작업 시작 전 `docs/progress.md`에서 상태와 선행 의존성을 먼저 확인한다.
- 담당 모듈 문서를 읽고, 범위 밖 수정은 하지 않는다.
- 구현 전에 `docs/plans/YYYY-MM-DD-module-x-name.md` 형식의 실행 계획 문서를 작성하거나 갱신한다.
- 설계와 구현 계획을 분리한 작업은 `docs/plans/YYYY-MM-DD-module-x-name-design.md`와 구현 계획 문서를 모두 남긴다.
- 계획 문서가 없으면 구현을 시작하거나 완료 처리하지 않는다.
- 작업 완료 후 `docs/progress.md`의 상태를 갱신한다.
- 작업 로그에는 `Plan:` 항목으로 해당 `docs/plans` 문서 경로를 남긴다.
- 선행 모듈 계약이 바뀌면, 구현보다 먼저 해당 문서를 갱신한다.

## 문서 목록

- `module-a-market.md`
- `module-b-indicator.md`
- `module-c-signal.md`
- `module-d-strategy.md`
- `module-e-signal-generator.md`
- `module-f-risk.md`
- `module-g-position.md`
- `module-h-execution.md`
- `module-i-lifecycle.md`
- `module-j-ports.md`
- `module-k-application-trade.md`
- `module-l-application-research.md`
- `module-m-application-strategy-lifecycle.md`
- `module-n-infrastructure-exchange.md`
- `module-o-infrastructure-persistence.md`
- `module-p-infrastructure-llm.md`
- `module-q-infrastructure-messaging.md`
- `module-r-interfaces-api.md`
- `module-s-interfaces-scheduler.md`
- `module-t-interfaces-websocket.md`
