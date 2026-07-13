# Deferred Strategy Registry Design

## Goal

Prevent failed or superseded strategy families from being selected by default in future research, while retaining their strategy implementations, scheduler features, and use cases for reproducibility.

## Classification

- `failed`: authoritative OOS or screening evidence is negative.
- `deferred`: some positive behavior exists, but promotion evidence is insufficient.
- `superseded`: the recorded run was invalidated by a later data or feature-semantics correction.

Each family records its candidate group, candidate-id patterns, evidence files, decision reason, and explicit revisit conditions. The registry is the source of truth for research prioritization, not a live-trading blocklist.

## Runtime Behavior

Both scheduler-driven backtest CLIs reject registered candidate groups by default. Reproduction requires an explicit `--include-deferred` flag. Programmatic candidate selection applies the same gate so future automation cannot accidentally bypass the policy.

The candidate factories and domain strategy implementations remain in place. Shared Binance loaders, scheduler paths, guards, sizing, TP/SL, and max-holding features are not removed.

## Artifact Retention

Keep consolidated decision summaries, final strict WFV reports, and the final reproducibility row set. Delete family-level A/B shards, obsolete pre-fix runs, and duplicate large JSON/JSONL payloads. The registry links only to retained evidence.

## Verification

Tests must prove that registered groups fail without opt-in, succeed with opt-in, and that both CLIs expose the explicit replay flag. Existing candidate construction tests remain to prove the implementations were not deleted.
