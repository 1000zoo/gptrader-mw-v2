# Module P Infrastructure LLM Design

## Goal

Build a vendor-neutral LLM infrastructure boundary that future LLM-backed strategies can use without exposing SDK, HTTP, prompt, or parsing details to `domain` or `application`.

## Architecture

Module P stays inside `src/infrastructure/llm` and provides three responsibilities:

- `prompt_builder.py` converts a `StrategyContext` plus strategy instructions into structured chat messages.
- `llm_client.py` wraps an injected low-level model client and translates transport/model failures into infrastructure contract errors.
- `response_parser.py` parses strict JSON model output into existing domain `StrategyResult`, `Signal`, and `SignalReason` values.

This module does not add new domain rules. The existing `StrategyContext`, `StrategyResult`, and signal models remain the contract language. Future LLM strategies can compose these infrastructure helpers at the composition root or in strategy implementation modules without importing a vendor SDK into domain or application code.

## Components

### Prompt Builder

`PromptBuilder` accepts:

- a strategy name
- plain strategy instructions
- a `StrategyContext`

It returns immutable `PromptMessage` values with `role` and `content`. The prompt includes symbol, timeframe, latest OHLCV, indicator values, and metadata in deterministic JSON so tests and logs are stable.

### LLM Client

`LLMClient` accepts an injected callable/model client. It sends prompt messages with a model name and timeout seconds. It returns plain text content. Any low-level exception or malformed response is raised as `LLMClientError`.

The implementation deliberately avoids importing OpenAI, Anthropic, or other vendor packages. A concrete vendor object can be passed in later from configuration code.

### Response Parser

`ResponseParser` accepts strict JSON text:

```json
{
  "direction": "long",
  "confidence": "0.82",
  "reasons": [{"code": "trend", "message": "Momentum confirmed"}],
  "metadata": {"model": "example"}
}
```

It validates direction and confidence through existing domain models and returns `StrategyResult`. JSON syntax errors, missing fields, invalid directions, and invalid domain values are translated to `LLMResponseParseError`.

## Error Handling

Infrastructure errors use this module's contract language:

- `LLMClientError` for request/response execution failures.
- `LLMResponseParseError` for invalid or unusable model output.

These errors prevent SDK/HTTP/JSON exceptions from leaking upward.

## Testing

Tests cover:

- deterministic prompt message construction from a real `StrategyContext`
- injected low-level client invocation and plain text extraction
- low-level client failure translation
- JSON response parsing into `StrategyResult`
- invalid model response translation to `LLMResponseParseError`

