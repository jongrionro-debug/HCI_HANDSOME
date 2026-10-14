"""Build a privacy-preserving and deterministic model context.

``build_context`` consumes a store snapshot rather than reaching into a store.
That keeps ownership, request lifetime, expiration, and revision checks in the
calling application while making the model-facing payload deterministic and
small enough to inspect in tests.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from .errors import StyleMateError
from .registry import FEATURES, REGISTRY_VERSION, category_for_garment_type, validate_values


_SUPPORTED_FACTS = {"occasion", "activity", "goal"}
_SCOPES = {"short_term", "long_term"}
_POLARITIES = {"prefer", "avoid", "require"}
_STRENGTHS = {"soft", "hard"}


def _now(snapshot: dict[str, Any]) -> datetime:
    value = snapshot.get("now")
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = _parse_time(value)
    else:
        result = datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be an ISO-8601 string")
    normalised = value.replace("Z", "+00:00")
    result = datetime.fromisoformat(normalised)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def _time_active(memory: dict[str, Any], now: datetime) -> tuple[bool, str | None]:
    for field, before in (("valid_from", False), ("valid_until", True), ("retention_until", True)):
        value = memory.get(field)
        if value in (None, ""):
            continue
        try:
            timestamp = _parse_time(value)
        except ValueError:
            return False, f"invalid_{field}"
        if before and now >= timestamp:
            return False, "expired"
        if not before and now < timestamp:
            return False, "not_yet_valid"
    return True, None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _memory_id(memory: dict[str, Any]) -> str | None:
    value = memory.get("id")
    return value if isinstance(value, str) and value else None


def _target_matches(memory: dict[str, Any], target: dict[str, Any]) -> bool:
    selector = memory.get("selector") or {}
    if not isinstance(selector, dict):
        return False
    garment_type = selector.get("garment_type")
    slot_id = selector.get("slot_id")
    if garment_type is not None and garment_type != target.get("garment_type"):
        return False
    if slot_id is not None and slot_id != target.get("target_id", target.get("id")):
        return False
    # An unknown selector key is intentionally treated as non-matching.  It
    # avoids broadening an item-specific memory when a future schema appears.
    return all(key in {"garment_type", "slot_id"} for key in selector)


def _conditions_match(memory: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, str | None]:
    conditions = memory.get("conditions") or {}
    if not isinstance(conditions, dict):
        return False, "invalid_conditions"
    for key, expected in conditions.items():
        if key not in _SUPPORTED_FACTS:
            return False, "unsupported_condition"
        actual = facts.get(key)
        if actual is None:
            return False, "condition_unknown"
        if isinstance(actual, list):
            if expected not in actual:
                return False, "condition_mismatch"
        elif str(actual) != str(expected):
            return False, "condition_mismatch"
    return True, None


def _fact_scope_matches(scope: Any, target: dict[str, Any] | None) -> bool:
    if scope in (None, "global"):
        return True
    if target is None or not isinstance(scope, dict):
        return False
    target_id = scope.get("slot_id", scope.get("target_id"))
    if target_id is not None and target_id != target.get("target_id"):
        return False
    garment_type = scope.get("garment_type")
    if garment_type is not None and garment_type != target.get("garment_type"):
        return False
    return all(key in {"garment_type", "slot_id", "target_id", "level", "category"} for key in scope)


def _resolve_fact_sources(
    fact_sources: list[dict[str, Any]],
    target: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project facts with deterministic scope/origin precedence.

    Sources with the same feature and equal priority must agree.  When they do
    not, none of their values becomes operative; the returned conflict record
    remains available for a clarification question and audit provenance.
    """

    pending = [
        source for source in fact_sources
        if isinstance(source, dict)
        and not source.get("conflict")
        and _fact_scope_matches(source.get("target_scope"), target)
    ]
    result: dict[str, Any] = {}
    unresolved: list[dict[str, Any]] = []
    while pending:
        eligible: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        for source in pending:
            ok, reason = _conditions_match({"conditions": source.get("conditions") or {}}, result)
            if ok:
                eligible.append(source)
            elif reason == "condition_unknown":
                deferred.append(source)
        groups: dict[str, list[dict[str, Any]]] = {}
        for source in eligible:
            fact = source.get("fact")
            if isinstance(fact, str) and fact:
                groups.setdefault(fact, []).append(source)
        changed = False
        for fact, sources in groups.items():
            def priority(source: dict[str, Any]) -> tuple[int, int]:
                return (
                    2 if source.get("scope") in {"short_term", "current_input"} else 1,
                    2 if source.get("origin") in {"explicit", "current_input"} else 1,
                )

            top_priority = max(priority(source) for source in sources)
            top = [source for source in sources if priority(source) == top_priority]
            values = {_canonical(source.get("value")) for source in top}
            if len(values) > 1:
                source_ids = sorted({source_id for source in top for source_id in source.get("source_ids", []) if isinstance(source_id, str)})
                unresolved.append({"feature": fact, "reason": "same_priority_fact_conflict", "source_ids": source_ids})
                changed = True
                continue
            # Stable source ID ordering prevents input order from deciding the
            # representative when values are equivalent.
            representative = sorted(top, key=lambda source: _canonical(source.get("source_ids", [])))[0]
            result[fact] = deepcopy(representative.get("value"))
            changed = True
        # Remove resolved feature groups from the next pass.  Deferred facts
        # can become usable after another feature was resolved.
        resolved_facts = set(groups)
        pending = [source for source in deferred if source.get("fact") not in resolved_facts]
        if not changed:
            break
    return result, unresolved


def _facts_from_sources(
    fact_sources: list[dict[str, Any]],
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper returning only operative fact values."""

    return _resolve_fact_sources(fact_sources, target)[0]


def _sanitise_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Drop identity and provider-only fields from a memory copy."""

    allowed = {
        "id",
        "request_id",
        "scope",
        "feature",
        "values",
        "polarity",
        "strength",
        "match",
        "selector",
        "conditions",
        "content",
        "origin",
        "confirmed",
        "status",
        "version",
        "family_id",
        "created_at",
        "valid_from",
        "valid_until",
        "retention_until",
        "evidence_ref",
        "consent_ref",
    }
    return {key: deepcopy(value) for key, value in memory.items() if key in allowed}


def _sanitise_request(request: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "revision", "timezone", "status", "kind", "created_at", "updated_at"}
    return {key: deepcopy(value) for key, value in request.items() if key in allowed}


def _fact_context(facts: Any) -> dict[str, Any]:
    """Keep only explicitly confirmed situation facts.

    The helper accepts either ``{"occasion": "meeting"}`` or a mapping whose
    values are ``{"value": ..., "confirmed": True}`.  Unconfirmed entries
    are kept out of the provider payload and become questions at the caller.
    """

    if not isinstance(facts, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in facts.items():
        if key not in _SUPPORTED_FACTS:
            continue
        if isinstance(value, dict):
            if value.get("confirmed") is not True:
                continue
            value = value.get("value")
        if value not in (None, "", [], {}):
            if not selector:
                # Selector-scoped input must not become a flat condition fact;
                # it is projected later per target from ``fact_sources``.
                result[key] = deepcopy(value)
    return result


def _external_fact_context(
    facts: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    """Validate caller-supplied situation facts before memory conditions.

    A fact with a condition is usable only when that condition is satisfied by
    an already confirmed external fact.  This deliberately prevents a
    conditional ``goal`` from becoming a fact merely because it was supplied
    in the same payload.
    """

    if not isinstance(facts, dict):
        return {}, [], []
    pending: list[tuple[str, Any]] = [
        (key, value) for key, value in facts.items() if key in _SUPPORTED_FACTS
    ]
    result: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    while pending:
        progress = False
        retry: list[tuple[str, Any]] = []
        for key, raw_value in pending:
            value = raw_value
            conditions: dict[str, Any] = {}
            confirmed = True
            source_id: str | None = None
            selector: dict[str, Any] | None = None
            if isinstance(value, dict):
                confirmed = value.get("confirmed") is True
                raw_mapping = raw_value
                value = raw_mapping.get("value")
                conditions = raw_mapping.get("conditions") or {}
                source_id = raw_mapping.get("source_id") if isinstance(raw_mapping.get("source_id"), str) else None
                selector = raw_mapping.get("selector") if isinstance(raw_mapping.get("selector"), dict) else None
                if "selector" in raw_mapping and selector is None:
                    excluded.append({"source_id": source_id or f"fact:{key}", "reason": "invalid_selector"})
                    progress = True
                    continue
                if selector is not None and any(key_name not in {"garment_type", "slot_id"} for key_name in selector):
                    excluded.append({"source_id": source_id or f"fact:{key}", "reason": "invalid_selector"})
                    progress = True
                    continue
            if not confirmed or value in (None, "", [], {}):
                excluded.append({"source_id": source_id or f"fact:{key}", "reason": "unconfirmed"})
                progress = True
                continue
            if not isinstance(conditions, dict):
                excluded.append({"source_id": source_id or f"fact:{key}", "reason": "invalid_conditions"})
                progress = True
                continue
            ok, reason = _conditions_match({"conditions": conditions}, result)
            if not ok:
                if reason == "condition_unknown":
                    retry.append((key, raw_value))
                else:
                    excluded.append({"source_id": source_id or f"fact:{key}", "reason": reason or "condition_mismatch"})
                    progress = True
                continue
            result[key] = deepcopy(value)
            source = {
                "fact": key,
                "value": deepcopy(value),
                "source_ids": [source_id or f"fact:{key}"],
                "origin": "explicit",
                "source_type": "current_input",
                "scope": "current_input",
                "conditions": deepcopy(conditions),
            }
            raw_source_versions = raw_value.get("source_versions") if isinstance(raw_value, dict) else None
            if isinstance(raw_source_versions, list) and all(isinstance(version, (str, int)) and not isinstance(version, bool) for version in raw_source_versions):
                source["source_versions"] = deepcopy(raw_source_versions)
            elif isinstance(raw_value, dict) and isinstance(raw_value.get("source_version"), (str, int)) and not isinstance(raw_value.get("source_version"), bool):
                source["source_versions"] = [raw_value["source_version"]]
            if selector:
                source["target_scope"] = deepcopy(selector)
            sources.append(source)
            progress = True
        if not progress:
            for key, raw_value in retry:
                source_id = raw_value.get("source_id") if isinstance(raw_value, dict) and isinstance(raw_value.get("source_id"), str) else f"fact:{key}"
                excluded.append({"source_id": source_id, "reason": "condition_unknown"})
            break
        pending = retry
    return result, sources, excluded


def _situation_memory_facts(
    memories: list[Any],
    *,
    owner_id: str,
    request_id: str,
    now: datetime,
    base_facts: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    """Read the three situation keys without treating them as item features."""

    result: dict[str, Any] = {}
    ranked: dict[tuple[str, str], list[dict[str, Any]]] = {}
    excluded: list[dict[str, str]] = []
    fact_basis = base_facts or {}
    for memory in memories:
        if not isinstance(memory, dict) or memory.get("user_id") != owner_id:
            continue
        feature = memory.get("feature")
        if feature not in _SUPPORTED_FACTS or memory.get("status") != "active":
            continue
        selector = memory.get("selector") or {}
        if not isinstance(selector, dict) or any(key not in {"garment_type", "slot_id"} for key in selector):
            if isinstance(memory.get("id"), str):
                excluded.append({"source_id": memory["id"], "reason": "invalid_selector"})
            continue
        if memory.get("scope") == "short_term" and memory.get("request_id") != request_id:
            continue
        if memory.get("scope") == "long_term" and memory.get("request_id") is not None:
            continue
        active, _ = _time_active(memory, now)
        if not active:
            continue
        if memory.get("origin") not in {"explicit", "inferred"} or memory.get("confirmed") is not True:
            continue
        if memory.get("polarity") == "avoid":
            if isinstance(memory.get("id"), str):
                excluded.append({"source_id": memory["id"], "reason": "fact_avoid_unsupported"})
            continue
        if memory.get("polarity") not in {"prefer", "require"}:
            continue
        condition_ok, condition_reason = _conditions_match(memory, fact_basis)
        if not condition_ok:
            if condition_reason == "condition_unknown":
                # A scoped fact may be satisfied only after target projection
                # (for example a Pants-specific occasion).  Preserve it with
                # its conditions for the second pass below.
                pass
            elif isinstance(memory.get("id"), str):
                excluded.append({"source_id": memory["id"], "reason": condition_reason or "condition_unknown"})
                continue
        values = memory.get("values")
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
            continue
        selector_key = _canonical(selector)
        ranked.setdefault((feature, selector_key), []).append(memory)
    fact_sources: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    overridden: list[dict[str, str]] = []
    for (feature, _selector_key), candidates in ranked.items():
        candidates.sort(
            key=lambda item: (
                2 if item.get("scope") == "short_term" else 1,
                str(item.get("created_at") or ""),
                int(item.get("version") or 0),
            ),
            reverse=True,
        )
        top = candidates[0]
        top_key = (2 if top.get("scope") == "short_term" else 1, top.get("origin"))
        same_priority = [candidate for candidate in candidates if (
            2 if candidate.get("scope") == "short_term" else 1,
            candidate.get("origin"),
        ) == top_key]
        value_sets = {tuple(candidate.get("values") or []) for candidate in same_priority}
        source_ids = sorted({memory.get("id") for memory in same_priority if isinstance(memory.get("id"), str)})
        if len(value_sets) > 1:
            conflicts.append({"feature": feature, "reason": "same_priority_fact_conflict", "source_ids": source_ids})
            fact_sources.extend({
                "fact": feature,
                "value": deepcopy(candidate.get("values")),
                "source_ids": [candidate["id"]],
                "origin": candidate.get("origin"),
                "source_type": "memory",
                "scope": candidate.get("scope"),
                "conditions": deepcopy(candidate.get("conditions") or {}),
                "conflict": True,
                **({"source_versions": [candidate["version"]]} if isinstance(candidate.get("version"), (str, int)) and not isinstance(candidate.get("version"), bool) else {}),
                **({"target_scope": deepcopy(candidate.get("selector"))} if candidate.get("selector") else {}),
            } for candidate in same_priority if isinstance(candidate.get("id"), str))
            continue
        values = top.get("values") or []
        selected_value = deepcopy(values[0] if len(values) == 1 else values)
        if feature not in result:
            result[feature] = selected_value
        elif result[feature] != selected_value:
            prior = result[feature] if isinstance(result[feature], list) else [result[feature]]
            incoming = selected_value if isinstance(selected_value, list) else [selected_value]
            result[feature] = list(dict.fromkeys(prior + incoming))
        if isinstance(top.get("id"), str):
            fact_sources.append({
                "fact": feature,
                "value": selected_value,
                "source_ids": [top["id"]],
                "origin": top.get("origin"),
                "source_type": "memory",
                "scope": top.get("scope"),
                "conditions": deepcopy(top.get("conditions") or {}),
                **({"source_versions": [top["version"]]} if isinstance(top.get("version"), (str, int)) and not isinstance(top.get("version"), bool) else {}),
                **({"target_scope": deepcopy(top.get("selector"))} if top.get("selector") else {}),
            })
        for candidate in candidates[1:]:
            if isinstance(candidate.get("id"), str):
                overridden.append({"source_id": candidate["id"], "reason": "fact_lower_priority"})
    return result, fact_sources, conflicts, overridden, excluded


def _compact_registry() -> dict[str, Any]:
    """Expose model vocabulary without repeating design-time PDF metadata."""

    return {
        "version": REGISTRY_VERSION,
        "features": {
            feature: {
                "values": deepcopy(meta["values"]),
                "value_type": meta["value_type"],
                "applicable_categories": deepcopy(meta["applicable_categories"]),
                **({"by_garment_type": deepcopy(meta["by_garment_type"])} if feature == "length" else {}),
            }
            for feature, meta in FEATURES.items()
        },
    }


def _target_list(targets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise StyleMateError("invalid_target", "targets의 각 항목은 object여야 합니다")
        target_id = target.get("id", target.get("target_id"))
        garment_type = target.get("garment_type")
        if not isinstance(target_id, str) or not target_id.strip():
            raise StyleMateError("invalid_target", "target id가 필요합니다")
        if target_id in seen:
            raise StyleMateError("duplicate_target", f"중복 target입니다: {target_id}")
        if garment_type not in FEATURES["garment_type"]["values"]:
            raise StyleMateError("invalid_target", f"지원하지 않는 garment_type입니다: {garment_type}")
        seen.add(target_id)
        result.append({
            "target_id": target_id,
            "level": "item",
            "garment_type": garment_type,
            "category": category_for_garment_type(garment_type),
        })
    if not result:
        raise StyleMateError("empty_targets", "하나 이상의 target이 필요합니다")
    return result


def _validate_memory_shape(memory: dict[str, Any], target: dict[str, Any]) -> tuple[bool, str | None]:
    feature = memory.get("feature")
    if feature not in FEATURES:
        return False, "unsupported_feature"
    values = memory.get("values")
    match = memory.get("match", "any")
    try:
        validate_values(feature, values, match=match, garment_type=target.get("garment_type"))
    except StyleMateError as error:
        return False, error.code
    polarity = memory.get("polarity")
    strength = memory.get("strength")
    if polarity not in _POLARITIES:
        return False, "invalid_polarity"
    if strength not in _STRENGTHS:
        return False, "invalid_strength"
    if memory.get("scope") not in _SCOPES:
        return False, "invalid_scope"
    if memory.get("status") != "active":
        return False, "inactive"
    if memory.get("origin") not in {"explicit", "inferred"}:
        return False, "invalid_origin"
    return True, None


def _is_positive_scalar(memory: dict[str, Any]) -> bool:
    return (
        memory.get("polarity") in {"prefer", "require"}
        and memory.get("feature") not in {"style", "mood", "season", "functions"}
        and memory.get("match", "any") in {"any", "range"}
        and (len(memory.get("values") or []) == 1 or memory.get("match") == "range")
    )


def _memory_priority(memory: dict[str, Any]) -> tuple[int, int, str, int]:
    # Current explicit short-term conditions outrank the long-term base.
    return (
        2 if memory.get("scope") == "short_term" else 1,
        2 if memory.get("origin") == "explicit" else 1,
        str(memory.get("created_at") or ""),
        int(memory.get("version") or 0),
    )


def _make_binding(memory: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": target["target_id"],
        "feature": memory["feature"],
        "values": deepcopy(memory["values"]),
        "match": memory.get("match", "any"),
        "polarity": memory["polarity"],
        "strength": memory["strength"],
        "scope": memory.get("scope"),
        "source_ids": [memory_id] if (memory_id := _memory_id(memory)) else [],
    }


def _conflict_key(binding: dict[str, Any]) -> tuple[str, str, str]:
    return (binding["target_id"], binding["feature"], binding["polarity"])


def _resolve_bindings(
    entries: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    """Resolve target-local claims with current explicit scope precedence.

    ``hard`` describes constraint strength; it does not make a long-term claim
    outrank a confirmed current exception.  A current exception suppresses a
    conflicting long-term claim, while unrelated avoidance values coexist.
    Multiple conflicting current claims remain unresolved and become a
    question instead of being selected by input order.
    """

    grouped: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for memory, target in entries:
        grouped.setdefault((target["target_id"], memory["feature"]), []).append((memory, target))

    bindings: list[dict[str, Any]] = []
    overridden: list[dict[str, str]] = []
    questions: list[dict[str, str]] = []
    multi_features = {"style", "mood", "season", "functions"}

    def family_filter(candidates: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        candidates.sort(key=lambda item: _memory_priority(item[0]), reverse=True)
        seen: set[tuple[str, str]] = set()
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for memory, target in candidates:
            family = memory.get("family_id")
            family_key = (str(family), str(memory.get("polarity"))) if family else None
            if family_key and family_key in seen:
                if _memory_id(memory):
                    overridden.append({"source_id": _memory_id(memory), "reason": "duplicate_family"})
                continue
            if family_key:
                seen.add(family_key)
            result.append((memory, target))
        return result

    def values_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_values = set(left.get("values") or [])
        right_values = set(right.get("values") or [])
        overlap = bool(left_values & right_values)
        polarities = {left.get("polarity"), right.get("polarity")}
        if polarities == {"avoid"}:
            return False
        if "avoid" in polarities:
            return overlap
        # Positive scalar conditions with different values are alternatives
        # that cannot both be selected.  Match mode is part of the value's
        # meaning, so an any/range rewrite is also a conflict.
        if left.get("match", "any") != right.get("match", "any"):
            return True
        return not overlap

    def claims_conflict(left: dict[str, Any], right: dict[str, Any], feature: str) -> bool:
        if feature in multi_features:
            left_positive = left.get("polarity") in {"prefer", "require"}
            right_positive = right.get("polarity") in {"prefer", "require"}
            if left_positive and right_positive and not (set(left.get("values") or []) & set(right.get("values") or [])):
                return False
        return values_conflict(left, right)

    for (target_id, feature), raw_candidates in grouped.items():
        candidates = family_filter(raw_candidates)
        current = [item for item in candidates if item[0].get("scope") == "short_term" and item[0].get("origin") == "explicit"]
        pool = current if current else candidates
        if not pool:
            continue

        if feature in multi_features:
            # Positive labels coexist.  Conflicting same-value avoid/positive
            # claims remain a question; unrelated avoids stay in the set.
            conflicts = [
                (left, right)
                for index, left in enumerate(pool)
                for right in pool[index + 1:]
                if claims_conflict(left[0], right[0], feature)
            ]
        else:
            conflicts = [
                (left, right)
                for index, left in enumerate(pool)
                for right in pool[index + 1:]
                if values_conflict(left[0], right[0])
                and _memory_priority(left[0])[:2] == _memory_priority(right[0])[:2]
                and feature not in multi_features
            ]

        if conflicts:
            ids = [
                source_id
                for pair in conflicts
                for source_id in (_memory_id(pair[0][0]), _memory_id(pair[1][0]))
                if source_id
            ]
            questions.append({"target_id": target_id, "feature": feature, "reason": "same_priority_conflict", "source_ids": sorted(set(ids))})
            # Keep no executable binding for the disputed feature.  The valid
            # memories remain in context with question provenance.
            continue

        selected: list[tuple[dict[str, Any], dict[str, Any]]]
        if feature in multi_features:
            selected = list(pool)
        elif current:
            selected = list(current)
        else:
            top_memory, top_target = pool[0]
            selected = [(top_memory, top_target)]
            for memory, target in pool[1:]:
                if claims_conflict(top_memory, memory, feature):
                    mid = _memory_id(memory)
                    if mid:
                        overridden.append({"source_id": mid, "reason": "lower_priority"})
                else:
                    selected.append((memory, target))
        selected_ids = {_memory_id(memory) for memory, _target in selected if _memory_id(memory)}
        for memory, target in selected:
            bindings.append(_make_binding(memory, target))
        if current:
            for memory, _target in candidates:
                mid = _memory_id(memory)
                if mid and mid not in selected_ids:
                    # A lower-priority claim is suppressed only when it
                    # conflicts with a current exception; different avoids or
                    # preferences remain active together.
                    if any(claims_conflict(memory, current_memory, feature) for current_memory, _ in current):
                        overridden.append({"source_id": mid, "reason": "short_term_override"})
                    else:
                        bindings.append(_make_binding(memory, _target))
    # Deterministic order makes the context hash stable across store query
    # order and makes trimming predictable.
    bindings.sort(key=lambda item: (item["target_id"], item["feature"], item["polarity"], json.dumps(item["values"], ensure_ascii=False)))
    return bindings, overridden, questions


def _trim_context(context: dict[str, Any], char_budget: int) -> dict[str, Any]:
    if char_budget < 256:
        raise StyleMateError("invalid_budget", "char_budget는 256 이상이어야 합니다")

    def size() -> int:
        # This budget applies to user memory material and its target bindings.
        # Registry vocabulary/metadata is a separate provider token budget and
        # must not make an empty shopping context blocked.
        return len(_canonical({
            "memories": context.get("memories", []),
            "bindings": context.get("bindings", []),
            "facts": context.get("facts", {}),
            "facts_by_target": context.get("facts_by_target", {}),
            "fact_sources": context.get("fact_sources", []),
            "questions": context.get("questions", []),
        }))

    if size() <= char_budget:
        return context

    # Keep direct bindings and their source IDs first.  Model memories are
    # explanatory and can be shortened one item at a time.
    memories = context.get("memories", [])
    while memories and size() > char_budget:
        candidate = memories[-1]
        if candidate.get("scope") == "short_term" or candidate.get("strength") == "hard":
            # Find a removable long/soft item instead.
            index = next((i for i, item in enumerate(memories) if item.get("scope") == "long_term" and item.get("strength") != "hard"), None)
            if index is None:
                break
            candidate = memories[index]
            memories.pop(index)
        else:
            memories.pop()
        context.setdefault("excluded", []).append({"source_id": candidate.get("id"), "reason": "context_budget"})

    while context.get("bindings") and size() > char_budget:
        binding = context["bindings"][-1]
        if binding.get("strength") == "hard" or binding.get("scope") == "short_term":
            break
        context["bindings"].pop()
        for source_id in binding.get("source_ids", []):
            context.setdefault("excluded", []).append({"source_id": source_id, "reason": "context_budget"})

    if size() > char_budget:
        context["blocked"] = True
        context.setdefault("questions", []).append({"reason": "context_budget", "message": "핵심 기억을 모델에 전달할 수 없어 추론을 보류합니다."})
        # Do not silently remove hard/current bindings; consumers can show this
        # status and ask for a smaller request.
    return context


def build_context(
    snapshot: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    facts: dict[str, Any] | None = None,
    char_budget: int = 6000,
    long_limit: int = 12,
    short_limit: int = 20,
) -> dict[str, Any]:
    """Build a model-facing context from a trusted store snapshot.

    The result never includes ``user_id`` or a foreign memory's ID/content.
    The caller must re-check the snapshot/profile revision before applying a
    model response.
    """

    if not isinstance(snapshot, dict):
        raise StyleMateError("invalid_snapshot", "snapshot은 object여야 합니다")
    request = snapshot.get("request")
    if not isinstance(request, dict):
        raise StyleMateError("invalid_snapshot", "snapshot.request가 필요합니다")
    owner_id = request.get("user_id")
    request_id = request.get("id")
    if not isinstance(owner_id, str) or not owner_id:
        raise StyleMateError("invalid_snapshot", "snapshot.request.user_id가 필요합니다")
    if not isinstance(request_id, str) or not request_id:
        raise StyleMateError("invalid_snapshot", "snapshot.request.id가 필요합니다")
    if not isinstance(long_limit, int) or long_limit < 0 or not isinstance(short_limit, int) or short_limit < 0:
        raise StyleMateError("invalid_limit", "memory limit은 0 이상의 정수여야 합니다")

    target_list = _target_list(targets)
    now = _now(snapshot)
    raw_memories = snapshot.get("memories", [])
    if not isinstance(raw_memories, list):
        raise StyleMateError("invalid_snapshot", "snapshot.memories는 list여야 합니다")
    external_facts = facts if facts is not None else snapshot.get("facts")
    external_context_facts, external_fact_sources, external_fact_excluded = _external_fact_context(external_facts)
    confirmed_facts, fact_sources, fact_questions, fact_overridden, fact_excluded = _situation_memory_facts(
        raw_memories, owner_id=owner_id, request_id=request_id, now=now, base_facts=external_context_facts
    )
    fact_sources = external_fact_sources + fact_sources
    # Only unscoped sources become global facts.  Target-scoped evidence is
    # projected per item below and never flattened into this mapping.
    confirmed_facts, global_fact_conflicts = _resolve_fact_sources(
        [source for source in fact_sources if source.get("target_scope") in (None, "global")]
    )
    target_fact_resolutions = {
        target["target_id"]: _resolve_fact_sources(fact_sources, target)
        for target in target_list
    }
    fact_conflicts = list(global_fact_conflicts) + [
        conflict
        for resolutions in target_fact_resolutions.values()
        for conflict in resolutions[1]
    ]
    conflict_source_ids = {
        source_id
        for conflict in fact_conflicts
        for source_id in conflict.get("source_ids", [])
        if isinstance(source_id, str)
    }
    if conflict_source_ids:
        for source in fact_sources:
            if any(source_id in conflict_source_ids for source_id in source.get("source_ids", [])):
                source["conflict"] = True
        confirmed_facts, _ = _resolve_fact_sources(
            [source for source in fact_sources if source.get("target_scope") in (None, "global")]
        )
        target_fact_resolutions = {
            target["target_id"]: _resolve_fact_sources(fact_sources, target)
            for target in target_list
        }
    facts_by_target = {target_id: values for target_id, (values, _conflicts) in target_fact_resolutions.items()}
    for conflict in fact_conflicts:
        question = {
            "feature": conflict.get("feature"),
            "reason": conflict.get("reason", "same_priority_fact_conflict"),
            "source_ids": conflict.get("source_ids", []),
        }
        if question not in fact_questions:
            fact_questions.append(question)
    invalid_fact_ids: set[str] = set()
    for source in fact_sources:
        conditions = source.get("conditions") or {}
        source_ids = [source_id for source_id in source.get("source_ids", []) if isinstance(source_id, str)]
        if not conditions or not source_ids:
            continue
        scoped_targets = [
            target for target in target_list
            if _fact_scope_matches(source.get("target_scope"), target)
        ]
        if not scoped_targets and source.get("target_scope") in (None, "global"):
            scoped_targets = [None]
        checks = [
            (target, facts_by_target[target["target_id"]]) if target is not None else (None, confirmed_facts)
            for target in scoped_targets
        ]
        if not checks:
            invalid_fact_ids.update(source_ids)
            excluded_reason = "target_mismatch"
        else:
            outcomes = [_conditions_match({"conditions": conditions}, fact_values) for _target, fact_values in checks]
            if any(ok for ok, _reason in outcomes):
                continue
            excluded_reason = next((reason for _ok, reason in outcomes if reason), "condition_unknown")
            invalid_fact_ids.update(source_ids)
        for source_id in source_ids:
            record = {"source_id": source_id, "reason": excluded_reason}
            if record not in fact_excluded:
                fact_excluded.append(record)
    if invalid_fact_ids:
        fact_sources = [
            source for source in fact_sources
            if not any(source_id in invalid_fact_ids for source_id in source.get("source_ids", []))
        ]
        confirmed_facts, _ = _resolve_fact_sources(
            [source for source in fact_sources if source.get("target_scope") in (None, "global")]
        )
        facts_by_target = {
            target["target_id"]: _resolve_fact_sources(fact_sources, target)[0]
            for target in target_list
        }

    entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    candidate_memories: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = external_fact_excluded + fact_excluded
    memory_ids: set[str] = set()
    for raw in raw_memories:
        if not isinstance(raw, dict):
            continue
        memory = deepcopy(raw)
        mid = _memory_id(memory)
        if memory.get("user_id") != owner_id:
            # A foreign ID is itself sensitive, so report only an aggregate
            # reason and never include its ID/content in the provider context.
            excluded.append({"reason": "other_user"})
            continue
        if memory.get("scope") == "long_term" and memory.get("request_id") is not None:
            if mid:
                excluded.append({"source_id": mid, "reason": "long_term_request_bound"})
            continue
        if memory.get("feature") in _SUPPORTED_FACTS:
            # Situation memories are projected into ``facts`` above and are
            # intentionally not presented as item feature bindings.
            continue
        if memory.get("request_id") not in (None, request_id) and memory.get("scope") != "long_term":
            if mid:
                excluded.append({"source_id": mid, "reason": "different_request"})
            continue
        if memory.get("scope") not in _SCOPES:
            if mid:
                excluded.append({"source_id": mid, "reason": "invalid_scope"})
            continue
        if memory.get("status") != "active":
            if mid:
                excluded.append({"source_id": mid, "reason": memory.get("status") or "inactive"})
            continue
        active, reason = _time_active(memory, now)
        if not active:
            if mid:
                excluded.append({"source_id": mid, "reason": reason or "expired"})
            continue
        if memory.get("scope") == "short_term" and memory.get("request_id") != request_id:
            if mid:
                excluded.append({"source_id": mid, "reason": "different_request"})
            continue
        matched = False
        for target in target_list:
            if not _target_matches(memory, target):
                continue
            matched = True
            condition_ok, condition_reason = _conditions_match(memory, facts_by_target[target["target_id"]])
            if not condition_ok:
                if mid:
                    record = {"source_id": mid, "reason": condition_reason or "condition_unknown"}
                    if record not in excluded:
                        excluded.append(record)
                continue
            valid, shape_reason = _validate_memory_shape(memory, target)
            if not valid:
                if mid:
                    excluded.append({"source_id": mid, "reason": shape_reason or "invalid_memory"})
                continue
            if mid not in memory_ids:
                candidate_memories.append(memory)
                memory_ids.add(mid)
            entries.append((memory, target))
        if not matched and mid:
            excluded.append({"source_id": mid, "reason": "target_mismatch"})

    # Enforce per-scope limits before conflict resolution, preferring current
    # memories and hard constraints.  Limits are a context budget policy, not a
    # deletion policy.
    def rank(memory: dict[str, Any]) -> tuple[int, int, str, int]:
        return (
            2 if memory.get("strength") == "hard" else 1,
            2 if memory.get("origin") == "explicit" else 1,
            str(memory.get("created_at") or ""),
            int(memory.get("version") or 0),
        )

    kept: list[dict[str, Any]] = []
    for scope, limit in (("long_term", long_limit), ("short_term", short_limit)):
        scoped = sorted((m for m in candidate_memories if m.get("scope") == scope), key=rank, reverse=True)
        kept.extend(scoped[:limit])
        for memory in scoped[limit:]:
            if _memory_id(memory):
                excluded.append({"source_id": _memory_id(memory), "reason": f"{scope}_limit"})
    keep_ids = {_memory_id(memory) for memory in kept}
    entries = [(memory, target) for memory, target in entries if _memory_id(memory) in keep_ids]
    bindings, overridden, conflict_questions = _resolve_bindings(entries)
    binding_ids = {source_id for binding in bindings for source_id in binding.get("source_ids", [])}
    conflict_ids = {
        source_id
        for question in conflict_questions
        for source_id in question.get("source_ids", [])
        if isinstance(source_id, str)
    }
    # Keep the active claims behind an unresolved conflict as explanation, but
    # do not create bindings from them.  This lets a model ask a useful
    # question without silently selecting one side.
    kept = [
        memory
        for memory in kept
        if _memory_id(memory) in binding_ids
        or _memory_id(memory) in conflict_ids
        or not _is_positive_scalar(memory)
    ]

    questions: list[dict[str, Any]] = list(fact_questions) + list(conflict_questions)
    unknown_conditions = [item for item in excluded if item.get("reason") == "condition_unknown" and item.get("source_id")]
    if unknown_conditions:
        questions.append({"reason": "condition_unknown", "source_ids": [item["source_id"] for item in unknown_conditions]})

    fact_sources.sort(key=_canonical)
    excluded.sort(key=_canonical)
    fact_questions.sort(key=_canonical)
    fact_overridden.sort(key=_canonical)
    overridden.sort(key=_canonical)
    questions.sort(key=_canonical)
    conflicted_source_ids = {
        source_id
        for source in fact_sources
        if source.get("conflict")
        for source_id in source.get("source_ids", [])
        if isinstance(source_id, str)
    }
    for source_id in sorted(conflicted_source_ids):
        record = {"source_id": source_id, "reason": "fact_conflict"}
        if record not in excluded:
            excluded.append(record)
    excluded.sort(key=_canonical)
    fact_sources = [source for source in fact_sources if not source.get("conflict")]

    context: dict[str, Any] = {
        "snapshot": {
            "request": _sanitise_request(request),
            "profile_revision": snapshot.get("profile_revision"),
            "now": now.isoformat(),
        },
        "registry_version": REGISTRY_VERSION,
        "registry": _compact_registry(),
        "targets": target_list,
        "memories": [_sanitise_memory(memory) for memory in sorted(kept, key=lambda item: str(item.get("id") or ""))],
        "bindings": bindings,
        "facts": confirmed_facts,
        "facts_by_target": facts_by_target,
        "fact_sources": fact_sources,
        "questions": questions,
        "excluded": excluded,
        "overridden": fact_overridden + overridden,
        "blocked": False,
    }
    # Include a compact request view for adapters while avoiding identity.
    context["request"] = _sanitise_request(request)
    context["profile_revision"] = snapshot.get("profile_revision")
    context = _trim_context(context, char_budget)
    unsigned = deepcopy(context)
    # ``now`` is retained for audit/debugging but is not itself an identity
    # input.  A digest changes when expiry alters the selected memories or
    # bindings, while repeated builds in the same state keep one context ID.
    unsigned.get("snapshot", {}).pop("now", None)
    context_hash = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    context["context_hash"] = context_hash
    context["context_id"] = f"ctx_{context_hash[:16]}"
    return context
