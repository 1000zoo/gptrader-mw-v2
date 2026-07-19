# LLM Client Response Shape Is Too Narrow

- Severity: `low`
- Status: `resolved`
- Found: `2026-05-25`

## Summary

`LLMClient` extracts text only from a raw string response or a mapping with a top-level `content` string. That matches the current unit tests, but it does not cover common SDK response shapes such as nested chat choices or response objects exposing text through attributes.

## Evidence

- `src/infrastructure/llm/llm_client.py:36` starts response extraction.
- `src/infrastructure/llm/llm_client.py:40` only handles `Mapping`.
- `src/infrastructure/llm/llm_client.py:41` only checks top-level `content`.
- `docs/plans/2026-05-24-module-p-infrastructure-llm.md` describes a vendor-neutral wrapper around injected low-level model clients.

## Impact

A real low-level client can successfully return model text while this wrapper raises `LLMClientError("LLM response did not include text content")`. That makes the boundary vendor-neutral in type but brittle in runtime adapters unless every caller wraps SDK output into the exact test shape first.

## Suggested Fix

Either document and enforce the injected callable contract as returning `str | {"content": str}`, or add small adapter/extractor support for the concrete SDK response shape used by the application. Add tests for the selected real response shape.

## Resolution

`LLMClient` now extracts text from plain strings, top-level mapping fields, chat-style `choices[].message.content`, choice `text`, and simple response objects exposing `output_text`, `text`, or `content` attributes.

## Verification

- `uv run pytest tests/application/usecases/trade/test_execute_trade_usecase.py tests/application/usecases/strategy_lifecycle/test_run_strategy_lifecycle_usecase.py tests/infrastructure/exchange/test_binance_order_execution_adapter.py tests/infrastructure/exchange/test_binance_account_adapter.py tests/infrastructure/llm/test_llm_client.py`
