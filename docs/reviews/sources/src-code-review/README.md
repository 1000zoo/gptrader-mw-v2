# Source Code Review Issues

이 문서는 `src` 하위 Python 코드 리뷰에서 발견한 이슈 후보를 추적한다.

## Review Scope

- Reviewed: `src/application`, `src/domain`, `src/infrastructure`, `src/interfaces`
- Supporting evidence: matching tests under `tests`
- Verification run: `uv run pytest` -> `165 passed`
- Found: `2026-05-25`

## Status Rules

- `open`: 아직 해결되지 않음
- `in progress`: 수정 작업 진행 중
- `resolved`: 수정 완료
- `won't fix`: 의도된 차이로 남김

## Issue List

| Issue | Severity | Status | Detail |
|-------|----------|--------|--------|
| Default risk policy cannot reject exhausted exposure before zero-quantity order creation | `important` | `resolved` | [../../by-type/runtime/exhausted-exposure-zero-quantity-order.md](../../by-type/runtime/exhausted-exposure-zero-quantity-order.md) |
| Position sync path is wired to an unimplemented Binance execution-report adapter | `important` | `resolved` | [../../by-type/runtime/binance-sync-position-unimplemented.md](../../by-type/runtime/binance-sync-position-unimplemented.md) |
| Binance account adapter method and payload shape are inconsistent | `medium` | `resolved` | [../../by-type/integration/binance-account-client-payload-mismatch.md](../../by-type/integration/binance-account-client-payload-mismatch.md) |
| Lifecycle default promotion can select an already-promoted evaluation | `medium` | `resolved` | [../../by-type/runtime/lifecycle-default-selects-promoted-evaluation.md](../../by-type/runtime/lifecycle-default-selects-promoted-evaluation.md) |
| LLM client text extraction does not match common SDK response shapes | `low` | `resolved` | [../../by-type/integration/llm-client-response-shape-too-narrow.md](../../by-type/integration/llm-client-response-shape-too-narrow.md) |
