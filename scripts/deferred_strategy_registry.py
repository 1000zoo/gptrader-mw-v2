from __future__ import annotations

import json
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "backtests"
    / "deferred-strategy-registry.json"
)
VALID_STATUSES = frozenset({"failed", "deferred", "superseded"})


@lru_cache(maxsize=1)
def load_deferred_strategy_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported deferred strategy registry schema")
    families = payload.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("deferred strategy registry must contain families")
    groups: set[str] = set()
    for family in families:
        if not isinstance(family, dict):
            raise ValueError("deferred strategy family must be an object")
        group = family.get("candidate_group")
        if not isinstance(group, str) or not group or group in groups:
            raise ValueError("deferred strategy candidate_group must be unique")
        groups.add(group)
        if family.get("status") not in VALID_STATUSES:
            raise ValueError(f"invalid deferred strategy status for {group}")
        for field in ("candidate_id_patterns", "evidence", "revisit_only_if"):
            value = family.get(field)
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                raise ValueError(f"{field} must be a non-empty string list for {group}")
        if not isinstance(family.get("reason"), str) or not family["reason"]:
            raise ValueError(f"reason must be provided for {group}")
    return payload


def deferred_candidate_groups() -> frozenset[str]:
    return frozenset(
        family["candidate_group"]
        for family in load_deferred_strategy_registry()["families"]
    )


def ensure_candidate_group_allowed(
    candidate_group: str,
    *,
    include_deferred: bool = False,
) -> None:
    if include_deferred or candidate_group not in deferred_candidate_groups():
        return
    relative_registry = REGISTRY_PATH.relative_to(Path(__file__).resolve().parents[1])
    raise ValueError(
        f"candidate group '{candidate_group}' is deferred; see {relative_registry.as_posix()} "
        "and pass --include-deferred only for intentional reproduction"
    )


def ensure_candidate_ids_allowed(
    candidate_ids: tuple[str, ...],
    *,
    include_deferred: bool = False,
) -> None:
    if include_deferred:
        return
    for candidate_id in candidate_ids:
        for family in load_deferred_strategy_registry()["families"]:
            if any(
                fnmatchcase(candidate_id, pattern)
                for pattern in family["candidate_id_patterns"]
            ):
                relative_registry = REGISTRY_PATH.relative_to(
                    Path(__file__).resolve().parents[1]
                )
                raise ValueError(
                    f"candidate '{candidate_id}' is deferred by group "
                    f"'{family['candidate_group']}'; see {relative_registry.as_posix()} "
                    "and opt in only for intentional reproduction"
                )
