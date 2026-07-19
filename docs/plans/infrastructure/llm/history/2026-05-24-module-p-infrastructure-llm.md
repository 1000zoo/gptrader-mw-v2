# Module P Infrastructure LLM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the first vendor-neutral LLM infrastructure boundary for prompt construction, model client wrapping, and response parsing.

**Architecture:** Keep all code under `src/infrastructure/llm` and depend only on standard library plus existing domain models. Use injected low-level model clients so no vendor SDK reaches `domain` or `application`. Translate model and parsing failures into local infrastructure exceptions.

**Tech Stack:** Python dataclasses, Protocol-style duck typing through injected callables, pytest.

---

### Task 1: Prompt Builder

**Files:**
- Create: `tests/infrastructure/llm/test_prompt_builder.py`
- Create: `src/infrastructure/llm/__init__.py`
- Create: `src/infrastructure/llm/prompt_builder.py`

**Step 1: Write the failing test**

Write a test that builds a real `StrategyContext`, calls `PromptBuilder.build(...)`, and asserts:

- two immutable `PromptMessage` values are returned
- the system message contains the strategy name and instructions
- the user message contains deterministic JSON with symbol, timeframe, latest candle, indicators, and metadata

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/llm/test_prompt_builder.py -v`

Expected: FAIL because `src.infrastructure.llm.prompt_builder` does not exist.

**Step 3: Write minimal implementation**

Create `PromptMessage` and `PromptBuilder` in `prompt_builder.py`. Use `json.dumps(..., sort_keys=True)` and convert `Decimal`/`datetime` values to strings.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/llm/test_prompt_builder.py -v`

Expected: PASS.

### Task 2: Response Parser

**Files:**
- Create: `tests/infrastructure/llm/test_response_parser.py`
- Create: `src/infrastructure/llm/response_parser.py`
- Modify: `src/infrastructure/llm/__init__.py`

**Step 1: Write the failing tests**

Add tests that assert:

- valid JSON parses into `StrategyResult`
- invalid JSON raises `LLMResponseParseError`
- missing or invalid fields raise `LLMResponseParseError`

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/llm/test_response_parser.py -v`

Expected: FAIL because parser code does not exist.

**Step 3: Write minimal implementation**

Implement `LLMResponseParseError` and `ResponseParser.parse(strategy_name, raw_text)`. Convert direction strings to `SignalDirection`, confidence to `Decimal`, reason dicts to `SignalReason`, and metadata to a dict.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/llm/test_response_parser.py -v`

Expected: PASS.

### Task 3: LLM Client

**Files:**
- Create: `tests/infrastructure/llm/test_llm_client.py`
- Create: `src/infrastructure/llm/llm_client.py`
- Modify: `src/infrastructure/llm/__init__.py`

**Step 1: Write the failing tests**

Add tests that assert:

- `LLMClient.generate(...)` passes model, messages, and timeout to an injected client
- text is extracted from string and mapping responses
- low-level exceptions raise `LLMClientError`
- missing text raises `LLMClientError`

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/llm/test_llm_client.py -v`

Expected: FAIL because client code does not exist.

**Step 3: Write minimal implementation**

Implement `LLMClientError` and `LLMClient`. Accept an injected callable with keyword arguments `model`, `messages`, and `timeout_seconds`. Convert `PromptMessage` values to plain role/content mappings.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/llm/test_llm_client.py -v`

Expected: PASS.

### Task 4: Module Completion

**Files:**
- Modify: `docs/progress.md`

**Step 1: Run focused tests**

Run: `uv run pytest tests/infrastructure/llm -v`

Expected: PASS.

**Step 2: Run full tests**

Run: `uv run pytest -q`

Expected: PASS.

**Step 3: Update progress board**

Set Module P to `done` and append a work log with both design and implementation plan paths.

