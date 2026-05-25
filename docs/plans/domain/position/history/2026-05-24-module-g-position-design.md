# Module G Position Design

## Goal

Define the pure domain language for current position state and position events.

## Scope

Module G owns only `src/domain/position` and `tests/domain/position`.
It does not call exchange APIs, websocket clients, persistence, or execution adapters.

## Recommended Approach

Use a minimal immutable domain model:

- `PositionStatus` represents whether a position is `OPEN` or `CLOSED`.
- `PositionEvent` represents domain-level position changes such as increase, decrease, and close.
- `Position` stores symbol, direction, quantity, average entry price, and status.
- Applying an event returns a new `Position`.

This keeps Module G usable by Module H execution contracts and Module T websocket handling without leaking infrastructure details into the domain.

## Data Model

`Position` uses:

- `Symbol` from Module A
- `SignalDirection` from Module C for long and short direction language
- `Decimal` for quantity and price

`PositionEvent` uses positive quantity values and optional fill price values. A close event may omit price because closing state does not require an average entry price recalculation.

## Rules

- Position quantity must be positive while open.
- Closed positions have zero quantity and `CLOSED` status.
- A position can only be opened with `LONG` or `SHORT`, not `WAIT`.
- Increase events must match the position direction and recalculate weighted average entry price.
- Decrease events reduce quantity and keep the existing average entry price.
- Decreasing by the full remaining quantity closes the position.
- Decreasing by more than the remaining quantity is rejected.
- Events cannot be applied to a closed position.

## Testing

Use TDD with focused tests for:

- opening a position
- rejecting invalid direction or quantity
- increasing with weighted average price
- decreasing partially
- closing by event
- rejecting over-reduction and updates after close
