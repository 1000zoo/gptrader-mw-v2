# Review Issue Index

이 문서는 `docs/reviews` 아래에 누적되는 리뷰 이슈를 한눈에 보기 위한 대표 파일이다.

## Directory Layout

- `by-type/`: 이슈 종류별 상세 문서
- `sources/`: 리뷰 출처별 요약 문서

## Issue Types

- `runtime`: 실행 경로에서 예외, 잘못된 상태, 잘못된 기본 동작을 만들 수 있는 이슈
- `integration`: 외부 SDK, 어댑터, 포트, 응답 형태처럼 경계 계약이 맞지 않는 이슈
- `persistence`: 저장소, DDL, 데이터 무결성 관련 이슈
- `test-coverage`: 검증 쿼리나 테스트 범위가 부족한 이슈
- `documentation`: 구현은 유효하지만 명시적 문서화가 필요한 이슈

## Maintenance Guidelines

다음 작업자는 이슈를 수정할 때 코드 변경만 남기지 말고, 리뷰 문서도 함께 갱신해야 한다.

- 처리 완료된 이슈는 `Open Issues` 표에서 제거하고 `Resolved Issues` 표로 옮긴다.
- `Resolved Issues`로 옮길 때 `Issue`, `Type`, `Severity`, `Source`, `Detail` 값은 기존 행과 동일하게 유지한다. 심각도나 분류를 바꾸려면 상세 문서에도 이유를 남긴다.
- 상세 문서에는 실제 수정 내용을 추적할 수 있도록 `Resolution`, `Fix`, `Verification` 같은 짧은 섹션을 추가한다. 최소한 어떤 파일/경로를 바꿨는지, 어떤 검증 명령을 실행했는지, 검증하지 못했다면 왜 못 했는지를 적는다.
- 이슈가 부분적으로만 완화된 경우에는 `Resolved Issues`로 옮기지 않는다. 대신 상세 문서에 남은 범위와 다음 작업자가 확인해야 할 조건을 적고, `Open Issues`에 계속 둔다.
- 원래 이슈와 다른 문제가 발견되면 기존 이슈 설명을 섞어 고치지 말고 새 상세 문서를 만든 뒤 `Open Issues`에 별도 행을 추가한다.
- 동일한 수정으로 여러 이슈가 닫히는 경우 각 상세 문서에 같은 수정 PR/커밋 또는 파일 경로를 각각 기록하고, 이 README의 모든 관련 행을 함께 이동한다.
- 리뷰 출처별 요약 문서(`sources/*/README.md`)가 있다면 상태 변화와 핵심 수정 내용을 그쪽에도 반영한다.
- 문서 링크는 이 README 기준 상대 경로를 사용한다. 새 상세 문서는 가능하면 `by-type/<type>/` 아래에 두고, 기존 분류와 파일명 스타일을 따른다.
- 검증 결과는 성공 여부만 쓰지 말고 실행한 명령을 그대로 남긴다. 예: `uv run pytest tests/...`.
- 수정 과정에서 이슈가 더 이상 재현되지 않는다는 근거가 부족하면 해결 처리하지 않는다. 재현 실패, 환경 차이, 외부 의존성 문제는 상세 문서에 명확히 남긴다.

## Open Issues

| Issue | Type | Severity | Source | Detail |
|-------|------|----------|--------|--------|
| _None_ |  |  |  |  |

## Resolved Issues

| Issue | Type | Severity | Source | Detail |
|-------|------|----------|--------|--------|
| Default risk policy cannot reject exhausted exposure before zero-quantity order creation | `runtime` | `important` | `src-code-review` | [by-type/runtime/exhausted-exposure-zero-quantity-order.md](by-type/runtime/exhausted-exposure-zero-quantity-order.md) |
| Position sync path is wired to an unimplemented Binance execution-report adapter | `runtime` | `important` | `src-code-review` | [by-type/runtime/binance-sync-position-unimplemented.md](by-type/runtime/binance-sync-position-unimplemented.md) |
| Binance account adapter method and payload shape are inconsistent | `integration` | `medium` | `src-code-review` | [by-type/integration/binance-account-client-payload-mismatch.md](by-type/integration/binance-account-client-payload-mismatch.md) |
| Lifecycle default promotion can select an already-promoted evaluation | `runtime` | `medium` | `src-code-review` | [by-type/runtime/lifecycle-default-selects-promoted-evaluation.md](by-type/runtime/lifecycle-default-selects-promoted-evaluation.md) |
| LLM client text extraction does not match common SDK response shapes | `integration` | `low` | `src-code-review` | [by-type/integration/llm-client-response-shape-too-narrow.md](by-type/integration/llm-client-response-shape-too-narrow.md) |
| SQLite text primary keys allow NULL | `persistence` | `important` | `sql-persistence` | [by-type/persistence/sqlite-text-primary-keys-null.md](by-type/persistence/sqlite-text-primary-keys-null.md) |
| Schema check omits generated indexes | `test-coverage` | `medium` | `sql-persistence` | [by-type/test-coverage/schema-check-missing-indexes.md](by-type/test-coverage/schema-check-missing-indexes.md) |
| Schema check is too shallow | `test-coverage` | `medium` | `sql-persistence` | [by-type/test-coverage/schema-check-shallow-coverage.md](by-type/test-coverage/schema-check-shallow-coverage.md) |
| Boolean spec to SQLite integer mapping is undocumented | `documentation` | `low` | `sql-persistence` | [by-type/documentation/boolean-sqlite-integer-mapping.md](by-type/documentation/boolean-sqlite-integer-mapping.md) |
| Binance LIMIT orders omit required timeInForce | `integration` | `important` | `binance-api-review` | [by-type/integration/binance-limit-order-missing-time-in-force.md](by-type/integration/binance-limit-order-missing-time-in-force.md) |
| Binance reduceOnly order parameter is encoded with unsafe futures semantics | `integration` | `important` | `binance-api-review` | [by-type/integration/binance-reduce-only-parameter-encoding.md](by-type/integration/binance-reduce-only-parameter-encoding.md) |
| Binance futures account mapper overstates usable collateral | `runtime` | `important` | `binance-api-review` | [by-type/runtime/binance-futures-account-collateral-mapping.md](by-type/runtime/binance-futures-account-collateral-mapping.md) |
| Binance REST trade errors are not classified for safe order reconciliation | `runtime` | `important` | `binance-api-review` | [by-type/runtime/binance-rest-trade-error-classification.md](by-type/runtime/binance-rest-trade-error-classification.md) |
| Binance REST boundary tests do not cover request construction and error paths | `test-coverage` | `medium` | `binance-api-review` | [by-type/test-coverage/binance-rest-boundary-test-gaps.md](by-type/test-coverage/binance-rest-boundary-test-gaps.md) |
| Binance config lacks explicit testnet mode | `documentation` | `low` | `binance-api-review` | [by-type/documentation/binance-config-explicit-testnet-mode.md](by-type/documentation/binance-config-explicit-testnet-mode.md) |

## Review Summaries

- [sources/src-code-review/README.md](sources/src-code-review/README.md)
- [sources/sql-persistence/README.md](sources/sql-persistence/README.md)
- [sources/binance-api-review/README.md](sources/binance-api-review/README.md)
