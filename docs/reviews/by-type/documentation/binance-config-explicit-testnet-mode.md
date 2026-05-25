# Binance Config Lacks Explicit Testnet Mode

- Severity: `low`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

`BinanceConfig` defaults to the live USD-M Futures base URL and can only target testnet through a raw `BINANCE_BASE_URL` override. There is no explicit testnet constructor, flag, or documented environment switch.

## Evidence

- `src/infrastructure/exchange/binance/binance_config.py:9` defaults `base_url` to `https://fapi.binance.com`.
- `src/infrastructure/exchange/binance/binance_config.py:18` reads `BINANCE_BASE_URL` from the environment.
- `docs/plans/infrastructure/exchange/latest.md:10` marks live Binance readiness as follow-up work.
- Binance official USD-M Futures General Info documents a separate REST base URL for testnet.

## Impact

Before live trading, operators need an obvious way to run the adapter against testnet. A raw base URL override works but is easy to misconfigure and is less clear in deployment manifests than an explicit testnet mode.

## Suggested Fix

Add a named constructor or environment flag such as `BINANCE_TESTNET=true` that selects the current USD-M Futures testnet REST base URL, while keeping `BINANCE_BASE_URL` as an explicit override. Document precedence and add tests for default, testnet, and override behavior.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`src/infrastructure/exchange/binance/binance_config.py` now supports `BINANCE_TESTNET=true`, which selects `https://testnet.binancefuture.com` unless `BINANCE_BASE_URL` is explicitly set. `docs/plans/infrastructure/exchange/latest.md` documents that precedence, and `tests/infrastructure/exchange/test_binance_rest.py` covers default, testnet, and override behavior.
