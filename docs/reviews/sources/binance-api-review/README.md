# Binance API Review Issues

이 문서는 `src/infrastructure/exchange/binance` 변경점과 관련 테스트/문서를 대상으로 한 Binance API 리뷰에서 발견한 이슈를 추적한다.

## Review Scope

- Reviewed: `src/infrastructure/exchange/binance`
- Supporting evidence: `tests/infrastructure/exchange/test_binance_*`, `docs/plans/infrastructure/exchange`
- Verification run: `uv run pytest tests/infrastructure/exchange -q` -> `8 passed`
- Found: `2026-05-26`

## Status Rules

- `open`: 아직 해결되지 않음
- `in progress`: 수정 작업 진행 중
- `resolved`: 수정 완료
- `won't fix`: 의도된 차이로 남김

## Issue List

| Issue | Severity | Status | Detail |
|-------|----------|--------|--------|
| Binance LIMIT orders omit required timeInForce | `important` | `resolved` | [../../by-type/integration/binance-limit-order-missing-time-in-force.md](../../by-type/integration/binance-limit-order-missing-time-in-force.md) |
| Binance reduceOnly order parameter is encoded with unsafe futures semantics | `important` | `resolved` | [../../by-type/integration/binance-reduce-only-parameter-encoding.md](../../by-type/integration/binance-reduce-only-parameter-encoding.md) |
| Binance futures account mapper overstates usable collateral | `important` | `resolved` | [../../by-type/runtime/binance-futures-account-collateral-mapping.md](../../by-type/runtime/binance-futures-account-collateral-mapping.md) |
| Binance REST trade errors are not classified for safe order reconciliation | `important` | `resolved` | [../../by-type/runtime/binance-rest-trade-error-classification.md](../../by-type/runtime/binance-rest-trade-error-classification.md) |
| Binance REST boundary tests do not cover request construction and error paths | `medium` | `resolved` | [../../by-type/test-coverage/binance-rest-boundary-test-gaps.md](../../by-type/test-coverage/binance-rest-boundary-test-gaps.md) |
| Binance config lacks explicit testnet mode | `low` | `resolved` | [../../by-type/documentation/binance-config-explicit-testnet-mode.md](../../by-type/documentation/binance-config-explicit-testnet-mode.md) |

## Resolution Notes

- Order mapping now sends `timeInForce=GTC` for LIMIT orders and omits `reduceOnly` unless it is true, in which case it is encoded as the Binance string value `true`.
- Futures account mapping now uses available futures collateral for `free`, initial margin for `locked`, and `totalMarginBalance` for account equity when present.
- Direct REST tests now cover unsigned GETs, signed POST form bodies, API key headers, rate-limit errors, unknown 503 order status, network errors, and invalid JSON.
- `BINANCE_TESTNET=true` selects the USD-M futures testnet base URL unless `BINANCE_BASE_URL` is explicitly set.
