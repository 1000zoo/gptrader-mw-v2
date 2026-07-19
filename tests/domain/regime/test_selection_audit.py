from datetime import datetime, timezone

import pytest

from src.domain.regime.selection import (
    AuditedSelectStrategyResult,
    RegimeSelectionState,
    SelectionAuditRecord,
    SelectionEventType,
    SelectStrategyResult,
)


def _base() -> SelectStrategyResult:
    state = RegimeSelectionState(
        symbol="BTCUSDT",
        artifact_version="a" * 64,
        current_cluster_fingerprint="component-a",
        active_strategy_profile_id="candidate-a",
        pending_cluster_fingerprint=None,
        pending_confirmation_count=0,
        consecutive_low_confidence_count=0,
        new_entries_enabled=True,
        last_boundary_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        state_version=1,
    )
    return SelectStrategyResult(
        expected_state_version=0,
        state=state,
        events=(SelectionEventType.CLASSIFICATION,),
        evaluated_artifact_identity="a" * 64,
        selection_input_hash="b" * 64,
    )


def test_selection_audit_record_is_deeply_immutable_canonical_and_roundtrips() -> None:
    source = {"reason": "selected", "nested": {"values": [2, 1]}}
    record = SelectionAuditRecord("daily_regime_selection", "v1", source)
    source["reason"] = "mutated"
    source["nested"]["values"].append(3)

    restored = SelectionAuditRecord.from_json(record.canonical_json)

    assert restored == record
    assert restored.audit_hash == record.audit_hash
    assert record.payload["reason"] == "selected"
    assert record.payload["nested"]["values"] == (2, 1)
    with pytest.raises(TypeError):
        record.payload["reason"] = "changed"


def test_audited_result_exposes_exact_base_contract_and_rejects_hash_mismatch() -> None:
    base = _base()
    record = SelectionAuditRecord(
        "daily_regime_selection",
        "v1",
        {"selection_input_hash": base.selection_input_hash, "reason": "selected"},
    )
    audited = AuditedSelectStrategyResult(base, record)

    assert audited.state is base.state
    assert audited.events is base.events
    assert audited.selection_input_hash == base.selection_input_hash
    with pytest.raises(ValueError, match="selection input hash"):
        AuditedSelectStrategyResult(
            base,
            SelectionAuditRecord(
                "daily_regime_selection", "v1", {"selection_input_hash": "c" * 64}
            ),
        )
