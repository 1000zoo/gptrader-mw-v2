# Gptrader V3 Codex Charter

## Purpose

This document is the root coding charter for AI agents working on `gptrader v3`.

The goal of this project is to build a crypto futures trading system that:

- supports multiple strategies rather than one fixed strategy
- makes strategy replacement easy
- can use LLM-based decision support when needed

`v2` may be used as a reference, but `v3` is not a structural continuation of `v2`.
The purpose of this document is to prevent accidental carry-over of old architecture, weak abstractions, and implementation leakage.

## Core Directives

- `v3` may reference `v2`, but it must not inherit `v2` structure blindly.
- Code from `v2` may be migrated only when its domain meaning is still valid and its behavior is verified by `v3` tests.
- `domain` and `application` must not know infrastructure details.
- Replaceability is more important than short-term implementation convenience.
- Follow OCP. New behavior should prefer extension points over repeated modification of core flows.
- Upper layers depend on contracts. Lower layers implement those contracts.
- Layer violations are not allowed for speed or convenience.
- Tests must verify meaningful behavior. Shortcut tests written only to pass are forbidden.
- Names must reveal responsibility, not habit.

## Architecture Overview

The system is expected to support the following high-level flow:

1. Fetch market data
2. Compute features
3. Generate trading signal
4. Validate risk
5. Execute trade
6. Track and update positions through events

## Layer Rules

### `domain`

Allowed:

- entities such as `Position`, `Order`, `Signal`
- value objects
- domain rules such as calculation and validation
- repository interfaces
- minimal domain services when truly necessary

Forbidden:

- API calls
- ORM usage
- DB implementation details
- exchange SDK usage
- direct LLM calls
- complex orchestration and flow control

Rules:

- `domain` must not know external systems.
- `domain` expresses business meaning, invariants, and rules.
- If storage or retrieval is needed, only contracts belong here.

### `application`

Rules:

- `application` is responsible only for use case orchestration.
- It receives input, coordinates domain objects and ports, and returns results.
- If business logic grows inside `application`, move it into `domain`.
- `application` must not directly handle DB driver errors, HTTP client errors, or vendor SDK exceptions.
- `application` only handles failures expressed in use case or contract language.

### `infrastructure`

Rules:

- All concrete integrations with external systems belong here.
- Exchange clients, DB implementations, caches, messaging, LLM adapters, file access, and external API integrations belong here.
- Vendor details must be hidden behind contracts.
- Response formats, SDK types, retry behavior, parsing, and protocol details must not leak upward.
- Split adapters by responsibility when needed instead of creating one oversized integration module.

### `interfaces`

Rules:

- API, CLI, scheduler, consumer, and other entrypoints belong here.
- `interfaces` translates incoming requests into use case calls and maps results into outputs.
- `interfaces` must not contain business rules or infrastructure logic.

### Dependency Direction

- `interfaces -> application -> domain`
- `infrastructure` implements contracts required by upper layers
- upper layers must not directly instantiate concrete implementations
- dependency wiring must happen only in explicit composition points

## Recommended Top-Level Structure

```text
src/
  domain/
  application/
  infrastructure/
  interfaces/
  config/
  main.py
```

The top-level structure is layer-oriented.
Features should be placed within the proper layer, not used as an excuse to bypass boundaries.

## Shared Module Policy

- Generic folders such as `utils`, `helpers`, `common`, and `shared` are restricted.
- Reuse alone is not enough reason to promote code into a shared module.
- Prefer keeping code inside its local context first.
- Promote code only when all of the following are true:
  - it is genuinely reusable
  - it is not tightly bound to one domain context
  - its responsibility is clear from the name
  - it remains meaningful outside the original module
- Do not create junk-drawer shared modules.

## Naming Rules

- Class and module names must reveal responsibility.
- Do not default to vague suffixes such as `Service`, `Helper`, or `Util`.
- Postfixes are allowed only when they match the real responsibility.
- Names such as `Manager`, `Engine`, `Resolver`, `Calculator`, `Planner`, `Executor`, `Registry`, and `Factory` are acceptable only when the object actually does that work.
- File names follow the same rule.

Examples:

- bad: `signal_service.py`
- good: `signal_generator.py`, `signal_evaluator.py`, `signal_policy.py`

- bad: `position_manager.py`
- good: `position_tracker.py`, `position_sizer.py`, `position_reconciler.py`

### Method Naming and Comments

- Function and method naming can remain flexible.
- If a method's responsibility is not immediately obvious, add a short comment that explains what role it plays.
- Comments must explain intent or boundary, not narrate each line of implementation.

## Dependency Injection Rules

- Upper layers must not instantiate concrete implementations directly.
- Dependencies must be connected through constructor injection or explicit composition points.
- `domain` and `application` depend on contracts, not implementations.
- Hidden global singletons, implicit factories, and test-only shortcuts are forbidden.

## LLM Rules

- Treat LLMs like any other external dependency.
- `domain` and `application` must not call LLMs directly.
- LLM usage must be hidden behind contracts.
- Model selection, prompt construction, parsing, retry behavior, timeout policy, and failure handling belong to `infrastructure`.
- Upper layers must not know vendor SDK details, raw response formats, or prompt assembly details.
- Even when an LLM participates in a use case, the use case should deal only with contract-level input and output.

## Error Handling Rules

- Errors must be translated into the language of the layer where they are exposed.
- Each layer may handle only the failures it is supposed to understand.
- `application` must not directly branch on DB, HTTP, exchange SDK, or other infrastructure-specific exceptions.
- `infrastructure` must capture external failures and convert them into failures expressed by contracts.
- `domain` must not represent infrastructure failures. It should express only domain rule violations and invariant failures.
- Silent retries, swallowed failures, and log-only handling are forbidden.
- Recoverable failures and terminal failures should be visible in the contract or use case boundary.

Examples:

- bad: `application` branching on SQLAlchemy exceptions or exchange SDK exceptions
- good: `application` handling failures such as `OrderSubmissionFailed` or `MarketDataUnavailable`

## Testing Rules

- Tests must verify meaningful behavior.
- Tests written only to make the suite pass are forbidden.
- Tests should protect structure and preserve refactoring safety.
- Domain rules should be verified primarily with focused unit tests.
- Infrastructure behavior should be verified with contract tests or integration tests.
- When a feature touches external API, DB, broker, or other external dependencies, mocks or dependency injection are allowed.
- Mocks must be used to verify boundaries, not to fake confidence.
- Test layout must mirror the `src/` structure.

Examples:

- `src/domain/services/trade/...`
- `tests/domain/services/trade/...`

## Migration Rules

- `v2` is reference material, not a base architecture.
- Do not preserve `v2` structure without a clear reason.
- Code from `v2` may be brought into `v3` only when all conditions are met:
  - its domain meaning is still valid
  - it is rewritten to fit `v3` boundaries
  - its behavior is verified by `v3` tests
- Old convenience utilities, muddy abstractions, and unclear shared modules should be treated as removal candidates by default.
- When old logic is complex, extract the business meaning first and rebuild it inside the new boundaries.

## Coding Style Rules

- Prefer small responsibility units over oversized functions or modules.
- Do not create hidden global state.
- Avoid unexplained magic numbers and magic strings.
- Handle failure explicitly.
- Prefer good naming and clear structure over heavy comments.
- Use short comments only when intent or responsibility is not obvious from the code itself.
- Do not add abstractions for imaginary future needs.
- Add extension points only where replacement or repeated variation is real.
- When adding new behavior, prefer extending the system over repeatedly editing core code paths.

## Working Rule for AI Agents

When implementing a new feature or refactoring an old one, follow this order:

1. define the domain boundary first
2. define the contracts next
3. place orchestration in `application`
4. implement concrete adapters in `infrastructure`
5. expose the use case through `interfaces`
6. add meaningful tests that mirror `src/`

If a quick implementation requires a layer violation, the quick implementation is wrong.
