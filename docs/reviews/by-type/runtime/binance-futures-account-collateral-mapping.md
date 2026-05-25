# Binance Futures Account Mapper Overstates Usable Collateral

- Severity: `important`
- Status: `resolved`
- Found: `2026-05-26`

## Summary

The futures account mapper converts `walletBalance` into `AssetBalance.free` and `maintMargin` into `AssetBalance.locked`. In USD-M futures account payloads those fields do not mean freely deployable collateral and locked balance.

## Evidence

- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:16` maps per-asset `walletBalance` to domain `free`.
- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:18` maps `maintMargin` to domain `locked`.
- `src/infrastructure/exchange/binance/account/binance_account_mapper.py:25` maps account `totalWalletBalance` to `total_equity`.
- The local Binance API reference lists `totalMarginBalance`, `availableBalance`, and per-asset `availableBalance` in `docs/plans/infrastructure/exchange/binance-usdm-futures-api-spec-2026.md:181`.

## Impact

Risk and sizing code that consumes `AccountSnapshot` can treat wallet balance as available capital even when margin is tied up in positions or open orders. This can overstate deployable exposure and produce orders that should have been rejected or downsized.

## Suggested Fix

Decide the futures semantics of `AccountSnapshot` explicitly. A conservative mapping is to use account or asset `availableBalance` for free-like collateral, derive locked exposure from margin fields such as initial/open-order/position margin where available, and use `totalMarginBalance` for equity when unrealized PnL should be included. Add tests with realistic USD-M account payloads containing positions, open-order margin, and unrealized profit.

## Verification

- `uv run pytest tests/infrastructure/exchange -q` -> `18 passed`

## Resolution

`src/infrastructure/exchange/binance/account/binance_account_mapper.py` now maps futures `availableBalance` to domain `free`, initial margin fields to `locked`, and account `totalMarginBalance` to `total_equity` when those fields are present. `tests/infrastructure/exchange/test_binance_account_adapter.py` uses a futures payload with available balance and margin fields to verify the mapping.
