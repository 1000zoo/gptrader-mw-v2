# Messaging Infrastructure Latest Plan

- Source path: `src/infrastructure/messaging`
- Module: Q
- Status: `done` for notifier adapter boundary and operational message format.
- Governs: operational notification and messaging adapters.

## Current Plan

Messaging infrastructure provides isolated notifier adapters for operational alerts. It owns a small vendor-neutral `OperationalMessage` format and concrete Slack/Telegram delivery adapters.

Notification policy stays outside this module: callers decide which runtime failures, trade executions, or lifecycle events should create messages. Notifiers only format and deliver already-selected messages. Delivery failures are isolated by returning `NotificationResult` values instead of raising by default, so alert outages do not break trading, scheduling, or API request handling.

The first adapter boundary is intentionally infrastructure-local because no application/domain notification port has been introduced yet. A future port can wrap the same message/result types if alerting becomes part of application use case contracts.

## History

- 2026-06-11: Added operational message format plus Slack and Telegram notifier adapter plan.

## Follow-Up

- Decide first production alert policy: runtime failure alerts, trade execution alerts, lifecycle promotion alerts, or all of them.
- Wire notifier instances in the operational composition root once Module R runner/API scaffolding exists.

