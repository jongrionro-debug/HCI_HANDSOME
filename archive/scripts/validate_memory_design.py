#!/usr/bin/env python3
"""Validate the Accepted v0.2 memory contract and synthetic policy cases.

This review-time checker requires jsonschema 4.26.0 and Draft 2020-12
FormatChecker. It does not authenticate users, call an LLM, use a database,
perform HTTP, or purge a filesystem. Evidence and expected outcomes in the
fixture are trusted human-written oracles; passing this checker is not a claim
that a model correctly understands Korean or image intent.
"""

from __future__ import annotations

import argparse
import copy
import json
import hashlib
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "memory-contract.schema.json"
DEFAULT_CASES = ROOT / "schemas" / "examples" / "memory-cases.json"
VERSION = "0.2"
REQUIRED_CATEGORIES = {
    "today_exception", "resume_expired_clone", "initial_direct_image_empty",
    "fit_only_unknown_image", "repeat_confirm_approval_quote",
    "selective_save_all_unchecked_close", "exact_duplicate_conditional_difference",
    "long_replace_request_exclude", "irrelevant_conflict_no_results",
    "candidate_inactive_wrong_user_request", "retry_cas_late_batch_failure",
    "withdraw_delete_derived_reentry", "rq1_isolated_baseline_split",
}
ACTION_TYPES = {"create", "confirm", "promote", "replace", "withdraw", "add_evidence", "delete"}
MEMORY_STATES = {"candidate", "active", "superseded", "withdrawn"}
EXCLUSIVE_CLAIM_KEYS = {"fit", "formality", "occasion"}


class DesignError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DesignError(message)


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DesignError(f"invalid timestamp: {value!r}") from exc
    require(parsed.tzinfo is not None, f"timestamp has no timezone: {value!r}")
    return parsed


def load_schema_validator(schema_path: Path):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise DesignError(
            "jsonschema==4.26.0 is required; install with "
            f"python3 -m pip install -r {ROOT / 'scripts' / 'requirements-memory-design.txt'}"
        ) from exc
    checker = FormatChecker()
    require("date-time" in checker.checkers, "jsonschema date-time FormatChecker is unavailable; install rfc3339-validator==0.1.4")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=checker)


def schema_check(validator: Any, value: dict[str, Any], label: str) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.path) or "$"
        raise DesignError(f"schema invalid {label}.{path}: {error.message}")


def reject_full_snapshots(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        require("before" not in value and "after" not in value, f"full event snapshot at {path}")
        for key, child in value.items():
            reject_full_snapshots(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_full_snapshots(child, f"{path}[{index}]")


def validate_request(request: dict[str, Any]) -> None:
    try: ZoneInfo(request["timezone"])
    except ZoneInfoNotFoundError as exc: raise DesignError("unknown timezone") from exc
    created = parse_time(request["created_at"])
    activity = parse_time(request["last_activity_at"])
    retention = parse_time(request["retention_until"])
    expected = min(activity + timedelta(days=30), created + timedelta(days=90))
    require(retention == expected, f"retention formula mismatch: {request['id']}")
    require(created <= activity <= retention, f"request timestamps: {request['id']}")


def validate_evidence(item: dict[str, Any]) -> None:
    require(parse_time(item["occurred_at"]) <= parse_time(item["raw_retention_until"]), f"evidence retention: {item['input_ref']}")
    if item["kind"] == "image_feedback":
        require(item["image_id"] is not None, f"image_id missing: {item['input_ref']}")
    else:
        require(item["image_id"] is None, f"non-image image_id: {item['input_ref']}")
    snapshot = item["snapshot"]
    require(snapshot["content"].strip(), f"empty evidence content: {item['input_ref']}")
    require(snapshot["authorized_roles"], f"evidence authority missing: {item['input_ref']}")
    require("quote" not in item and "model_output" not in item and "prior_input" not in item, f"untrusted text field: {item['input_ref']}")


def evidence_ref(evidence: dict[str, dict[str, Any]], input_ref: str, snapshot_ref: str) -> dict[str, Any]:
    require(snapshot_ref in evidence, f"unknown evidence snapshot: {snapshot_ref}")
    item = evidence[snapshot_ref]
    require(item["input_ref"] == input_ref, f"evidence input/snapshot mismatch: {input_ref}")
    return item


def evidence_input(evidence: dict[str, dict[str, Any]], input_ref: str) -> dict[str, Any]:
    matches = [item for item in evidence.values() if item["input_ref"] == input_ref]
    require(matches, f"unknown evidence input: {input_ref}")
    metadata = [{key:item[key] for key in ("input_ref","user_id","request_id","occurred_at","kind")} for item in matches]
    require(all(item==metadata[0] for item in metadata), "inconsistent input event")
    return metadata[0]


def validate_memory(memory: dict[str, Any], requests: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], now: datetime) -> None:
    state = memory["lifecycle"]["state"]
    scope = memory["scope"]
    period=memory["applicability"]
    if period["valid_from"] and period["valid_until"]:
        require(parse_time(period["valid_from"]) < parse_time(period["valid_until"]), "invalid period")
    require(state in MEMORY_STATES, f"memory state: {memory['id']}")
    if scope["type"] == "short_term":
        require(scope["request_id"] in requests, f"unknown short request: {memory['id']}")
        require(requests[scope["request_id"]]["kind"] in {"onboarding", "styling"}, f"short request kind: {memory['id']}")
        require(requests[scope["request_id"]]["user_id"] == memory["user_id"], f"short request owner: {memory['id']}")
    else:
        approval = scope["approval"]
        source = evidence_ref(evidence, approval["input_ref"], approval["snapshot_ref"])
        require("long_term_approval" in source["snapshot"]["authorized_roles"], f"approval role missing: {memory['id']}")
        require(source["user_id"] == memory["user_id"] == approval["user_id"], f"approval owner mismatch: {memory['id']}")
        require(source["snapshot"]["content"] == memory["content"] and source["snapshot"]["condition"] == memory["applicability"]["condition"] and source["snapshot"]["period"] == memory["applicability"], f"approval payload mismatch: {memory['id']}")
        require(source["snapshot"]["claim"]==memory["claim"], "claim snapshot mismatch")
    verification = memory["verification"]
    if state == "candidate":
        require(scope["type"] == "short_term" and verification["state"] == "unconfirmed", f"candidate invariant: {memory['id']}")
    if state == "active" or scope["type"] == "long_term":
        require(verification["state"] == "confirmed", f"confirmed invariant: {memory['id']}")
    if verification["state"] == "confirmed":
        confirmation = verification["confirmation"]
        source = evidence_ref(evidence, confirmation["input_ref"], confirmation["snapshot_ref"])
        require("content_confirmation" in source["snapshot"]["authorized_roles"], f"confirmation role missing: {memory['id']}")
        require(source["user_id"] == memory["user_id"] == confirmation["user_id"], f"confirmation owner mismatch: {memory['id']}")
        require(source["snapshot"]["content"] == memory["content"] and source["snapshot"]["condition"] == memory["applicability"]["condition"] and source["snapshot"]["period"] == memory["applicability"], f"confirmation payload mismatch: {memory['id']}")
    else:
        require(verification["confirmation"] is None, f"unconfirmed memory has confirmation: {memory['id']}")
    require(memory["lineage"]["family_id"].strip(), f"memory family missing: {memory['id']}")
    for ref in memory["evidence"]:
        source = evidence_ref(evidence, ref["input_ref"], ref["snapshot_ref"])
        snapshot = source["snapshot"]
        applicability = memory["applicability"]
        require(ref["snapshot_ref"] == source["snapshot_id"], f"evidence snapshot mismatch: {memory['id']}")
        require(source["user_id"] == memory["user_id"], f"evidence owner mismatch: {memory['id']}")
        require(set(ref["roles"]) <= set(snapshot["authorized_roles"]), "evidence unauthorized role")
        require(snapshot["content"] == memory["content"], f"evidence content mismatch: {memory['id']}")
        require(snapshot["condition"] == applicability["condition"], f"evidence condition mismatch: {memory['id']}")
        require(snapshot["period"] == applicability, f"evidence period mismatch: {memory['id']}")
        require(snapshot["claim"]==memory["claim"], "claim snapshot mismatch")
        if source["kind"] == "image_feedback" and state == "active":
            require(memory["claim"]["key"] in snapshot["selected_aspects"], f"image aspect overreach: {memory['id']}")


def validate_lineage(memories: dict[str, dict[str, Any]], redactions=None) -> None:
    redactions=redactions or {}
    for memory in memories.values():
        lineage = memory["lineage"]
        source_id = lineage["source_memory_id"]
        if lineage.get("source_redacted",False):
            require(source_id is None and lineage["operation"] != "create", "redacted lineage")
            proof=redactions.get(lineage.get("source_redaction_id"))
            require(proof is not None and proof["memory_id"]==memory["id"] and proof["user_id"]==memory["user_id"] and proof["operation"]==lineage["operation"] and proof["version"]<=memory["version"], "unproven source redaction")
            continue
        if lineage["operation"] == "create":
            require(source_id is None, f"create source: {memory['id']}")
            continue
        require(source_id in memories and source_id != memory["id"], f"lineage source missing/self: {memory['id']}")
        source = memories[source_id]
        require(source["user_id"] == memory["user_id"], f"lineage owner: {memory['id']}")
        if lineage["operation"] == "promote":
            require(source["scope"]["type"] == "short_term", f"promote source state: {memory['id']}")
            require(source["lineage"]["family_id"] == lineage["family_id"], f"promote family: {memory['id']}")
            require(source["content"] == memory["content"] and source["applicability"] == memory["applicability"], f"promote payload: {memory['id']}")
        if lineage["operation"] == "replace":
            require(source["lineage"]["family_id"] != lineage["family_id"], f"replace family: {memory['id']}")
    for memory in memories.values():
        seen: set[str] = set(); current = memory
        while current["lineage"]["source_memory_id"] is not None and not current["lineage"].get("source_redacted",False):
            source_id = current["lineage"]["source_memory_id"]
            require(source_id not in seen, f"lineage cycle: {memory['id']}")
            seen.add(source_id); current = memories[source_id]


def component_score(memory: dict[str, Any], query: dict[str, Any]) -> int:
    key = memory["claim"]["key"]
    if key.startswith("free_text") or key not in set(query["mapped_keys"]):
        return 0
    components = []
    if key in query["target_keys"]:
        components.append(3)
    if set(memory["tags"]) & set(query["tags"]):
        components.append(2)
    if key in query["general_style_keys"]:
        components.append(1)
    return max(components, default=0)


def condition_state(memory: dict[str, Any], query: dict[str, Any]) -> str:
    for predicate in memory["applicability"]["predicates"]:
        if predicate["field"] not in query["facts"]:
            return "unknown"
        if query["facts"][predicate["field"]] != predicate["value"]:
            return "mismatch"
    return "match"


def claims_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["key"] != right["key"]:
        return False
    if left["polarity"] == "avoid" and right["polarity"] == "avoid":
        return False
    if left["polarity"] == "avoid" or right["polarity"] == "avoid":
        return left["value"] == right["value"]
    return left["key"] in EXCLUSIVE_CLAIM_KEYS and left["value"] != right["value"]


def applicability_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["predicates"] and right["predicates"]:
        left_pairs = {(item["field"], item["value"]) for item in left["predicates"]}
        right_pairs = {(item["field"], item["value"]) for item in right["predicates"]}
        if any(field == other_field and value != other_value for field, value in left_pairs for other_field, other_value in right_pairs):
            return False
    if left["valid_until"] and right["valid_from"] and parse_time(left["valid_until"]) <= parse_time(right["valid_from"]):
        return False
    if right["valid_until"] and left["valid_from"] and parse_time(right["valid_until"]) <= parse_time(left["valid_from"]):
        return False
    return True


def retrieve(memories: list[dict[str, Any]], evidence: dict[str, dict[str, Any]], request: dict[str, Any], query: dict[str, Any], now: datetime) -> dict[str, Any]:
    candidates: list[tuple[dict[str, Any], int]] = []
    excluded: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for memory in memories:
        state = memory["lifecycle"]["state"]
        if memory["user_id"] != request["user_id"]:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "wrong_owner"}); continue
        if memory["verification"]["state"] != "confirmed" and state != "candidate":
            excluded.append({"memory_id":memory["id"],"version":memory["version"],"reason":"not_confirmed"}); continue
        if state == "candidate":
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "candidate"}); continue
        if state in {"withdrawn", "superseded"}:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": state}); continue
        if request["status"] != "open":
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "request_closed"}); continue
        if memory["id"] in query.get("exclude_memory_ids", []):
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "request_excluded"}); continue
        if memory["scope"]["type"] == "short_term":
            if memory["scope"]["request_id"] != request["id"]:
                excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "wrong_request"}); continue
        if now >= parse_time(request["retention_until"]):
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "expired"}); continue
        if memory["scope"]["type"] == "long_term":
            approval_ref = memory["scope"]["approval"]
            approval = evidence_ref(evidence, approval_ref["input_ref"], approval_ref["snapshot_ref"])
            if now >= parse_time(approval["occurred_at"]) + timedelta(days=365):
                excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "expired"}); continue
        period = memory["applicability"]
        if period["valid_from"] and now < parse_time(period["valid_from"]):
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "expired"}); continue
        if period["valid_until"] and now >= parse_time(period["valid_until"]):
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "expired"}); continue
        if memory["scope"]["type"] == "long_term" and period["condition"] and not period["predicates"]:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "condition_unknown"}); unresolved.append(f"condition:{memory['id']}"); continue
        state_of_condition = condition_state(memory, query)
        if state_of_condition == "unknown":
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "condition_unknown"}); unresolved.append(f"condition:{memory['id']}"); continue
        if state_of_condition == "mismatch":
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "irrelevant"}); continue
        score = component_score(memory, query)
        if memory["scope"]["type"] == "short_term":
            score = max(score, 1)
        elif score == 0:
            if memory["claim"]["key"].startswith("free_text") or memory["claim"]["key"] not in set(query["mapped_keys"]):
                excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "condition_unknown"}); unresolved.append(f"claim:{memory['id']}")
            else:
                excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "irrelevant"})
            continue
        candidates.append((memory, score))

    # Collapse promote families before conflict evaluation. A family is one
    # logical claim; conflict is evaluated between representatives only.
    family_groups: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for memory, score in candidates:
        family_groups.setdefault(memory["lineage"]["family_id"], []).append((memory, score))
    candidates = []
    for family in family_groups.values():
        family.sort(key=lambda pair: (pair[0]["scope"]["type"] != "short_term", -parse_time(pair[0]["created_at"]).timestamp(), pair[0]["id"]))
        candidates.append(family[0])
        for duplicate, _ in family[1:]:
            excluded.append({"memory_id": duplicate["id"], "version": duplicate["version"], "reason": "duplicate_family"})

    overridden: list[str] = []
    same_scope_conflicts: set[str] = set()
    for left, _ in list(candidates):
        for right, _ in list(candidates):
            if left["id"] >= right["id"] or left["claim"]["key"] != right["claim"]["key"]:
                continue
            if not applicability_overlap(left["applicability"], right["applicability"]):
                continue
            if not claims_conflict(left["claim"], right["claim"]):
                continue
            if left["scope"]["type"] != right["scope"]["type"]:
                short = left if left["scope"]["type"] == "short_term" else right
                long = right if short is left else left
                overridden.append(long["id"])
                candidates = [(item, score) for item, score in candidates if item["id"] != long["id"]]
                excluded.append({"memory_id": long["id"], "version": long["version"], "reason": "conflict"})
            else:
                same_scope_conflicts.update({left["id"], right["id"]})
    for memory_id in same_scope_conflicts:
        memory = next(item for item in memories if item["id"] == memory_id)
        candidates = [(item, score) for item, score in candidates if item["id"] != memory_id]
        excluded.append({"memory_id": memory_id, "version": memory["version"], "reason": "conflict"})
    if same_scope_conflicts:
        unresolved.append("conflicting_claims")

    representatives = sorted(candidates, key=lambda pair: (pair[0]["scope"]["type"] != "short_term", -pair[1], -parse_time(pair[0]["created_at"]).timestamp(), pair[0]["id"]))
    short_count = long_count = content_chars = 0
    selected: list[tuple[dict[str, Any], int]] = []
    truncated = False
    for memory, score in representatives:
        if memory["scope"]["type"] == "short_term" and short_count >= 20:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "budget"}); truncated = True
            if memory["claim"]["strength"] == "hard":
                unresolved.append(f"hard_budget:{memory['id']}")
            continue
        if memory["scope"]["type"] == "long_term" and long_count >= 12:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "budget"}); truncated = True; continue
        item_chars = len(memory["content"]) + len(memory["applicability"]["condition"] or "")
        if content_chars + item_chars > 6000:
            excluded.append({"memory_id": memory["id"], "version": memory["version"], "reason": "budget"}); truncated = True
            if memory["scope"]["type"] == "short_term" and memory["claim"]["strength"] == "hard":
                unresolved.append(f"hard_budget:{memory['id']}")
            continue
        selected.append((memory, score)); content_chars += item_chars
        short_count += memory["scope"]["type"] == "short_term"; long_count += memory["scope"]["type"] == "long_term"
    return {"selected": selected, "excluded": excluded, "overridden": sorted(set(overridden)), "unresolved": unresolved, "truncated": truncated, "content_chars": content_chars}


def validate_context(context: dict[str, Any], memories: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], requests: dict[str, dict[str, Any]], queries: dict[str, Any], profile_revision: int) -> None:
    request = requests[context["request_id"]]
    require(context["request_revision"] == request["revision"], f"context request revision: {context['context_id']}")
    require(context["profile_revision"] == profile_revision, f"context profile revision: {context['context_id']}")
    result = retrieve(list(memories.values()), evidence, request, queries[context["context_id"]], parse_time(context["now"]))
    require([item["memory_id"] for item in context["used"]] == [item["id"] for item, _ in result["selected"]], f"context selection differs: {context['context_id']}")
    require({(item["memory_id"], item["reason"]) for item in context["excluded"]} == {(item["memory_id"], item["reason"]) for item in result["excluded"]}, f"context exclusions differ: {context['context_id']}")
    require(set(context["overridden"]) == set(result["overridden"]), f"context overrides differ: {context['context_id']}")
    require(context["truncated"] == result["truncated"] and context["content_chars"] == result["content_chars"], f"context budget differs: {context['context_id']}")
    require(context["short_limit"] == 20 and context["long_limit"] == 12 and context["char_budget"] == 6000, "context budget constants")
    require(context["unresolved"] == result["unresolved"], f"context unresolved differs: {context['context_id']}")
    for rank, (memory, score) in enumerate(result["selected"], 1):
        used = context["used"][rank - 1]
        require(used["rank"] == rank and used["score"] == score and used["version"] == memory["version"], f"context rank/version differs: {context['context_id']}")
        require(used["scope_type"]==memory["scope"]["type"] and used["family_representative"], "context scope/representative")


def checked_ref(ref, evidence, user_id, role=None, payload=None, request_id=None):
    source = evidence_ref(evidence, ref['input_ref'], ref['snapshot_ref'])
    require(source['user_id'] == user_id, 'evidence owner')
    require(set(ref.get('roles', [role] if role else [])) <= set(source['snapshot']['authorized_roles']), 'evidence unauthorized role')
    if role:
        require(role in source['snapshot']['authorized_roles'], f'consent required: {role}')
    if request_id is not None:
        require(source['request_id'] == request_id, 'evidence request boundary')
    if payload is not None:
        require(source['snapshot']['content'] == payload['content'] and source['snapshot']['period'] == payload['applicability'], 'evidence payload mismatch')
    return source


def semantic_identity(item):
    return (json.dumps(item['claim'], sort_keys=True), json.dumps(item['applicability'], sort_keys=True), item['scope']['type'], item['scope'].get('request_id'))


def stage_batch(batch, memories, evidence, requests, profile_revision, current_input_ref, fail_after=None, redactions=None):
    """Independent review model: stage a complete batch, never mutate its input."""
    require(batch['cause_input_ref']==current_input_ref, 'current input mismatch')
    require(not any(a['type']=='delete' for a in batch['actions']) or all(a['type']=='delete' for a in batch['actions']), 'mixed deletion batch')
    require(batch['profile_revision'] == profile_revision, 'stale profile')
    if batch['request_id'] is not None:
        req = requests.get(batch['request_id'])
        require(req is not None and req['user_id'] == batch['user_id'], 'batch request owner')
        require(req['revision'] == batch['expected_request_revision'], 'stale request revision')
        require(req['status'] == 'open', 'request closed')
        require(parse_time(batch['issued_at']) < parse_time(req['retention_until']), 'request expired')
    for memory_id, version in batch['expected_versions'].items():
        require(memory_id in memories and memories[memory_id]['user_id'] == batch['user_id'], 'batch target owner')
        require(memories[memory_id]['version'] == version, 'stale version')
    staged = copy.deepcopy(memories)
    generated_redactions=copy.deepcopy(redactions or {})
    outputs, seen, cause = {}, set(), set()
    for index, action in enumerate(batch['actions']):
        require(action['action_id'] not in seen and set(action['depends_on']) <= seen, 'invalid dependency')
        seen.add(action['action_id'])
        target = action['target']
        target_id = None
        if target['kind'] == 'memory':
            target_id = target['memory_id']
            require(target_id in staged and staged[target_id]['user_id'] == batch['user_id'], 'batch target owner')
            require(target_id in batch['expected_versions'], 'missing expected version')
        elif target['kind'] == 'output':
            require(target['action_id'] in action['depends_on'] and target['action_id'] in outputs, 'invalid output dependency')
            target_id = outputs[target['action_id']]
        role = {'create':'content','confirm':'content_confirmation','promote':'long_term_approval',
                'replace':'replacement','withdraw':'withdrawal','add_evidence':'content','delete':'deletion'}[action['type']]
        require(action['evidence'], 'missing evidence')
        sources = [checked_ref(ref, evidence, batch['user_id'], request_id=batch['request_id']) for ref in action['evidence']]
        require(any(role in src['snapshot']['authorized_roles'] for src in sources), f'consent required: {role}')
        require(all(parse_time(src['occurred_at']) <= parse_time(batch['issued_at']) for src in sources), 'future evidence')
        require(all(src['input_ref']==current_input_ref for src in sources),'past evidence is not current consent')
        cause.update(src['input_ref'] for src in sources)
        require(len(cause) == 1, 'mixed current input')
        src = next(src for src in sources if role in src['snapshot']['authorized_roles'])
        current = staged.get(target_id)
        if action['type'] in {'create','replace'}:
            new = copy.deepcopy(action['new_item'])
            require(new is not None and new['id'] not in staged and new['version'] == 1, 'new identity/version')
            require(not new['lineage'].get('source_redacted',False),'new redacted source forbidden')
            validate_memory(new, requests, evidence, parse_time(batch['issued_at']))
            require(new['user_id'] == batch['user_id'], 'new item owner')
            require(src['snapshot']['content'] == new['content'] and src['snapshot']['period'] == new['applicability'], 'evidence payload mismatch')
            if new['scope']['type']=='short_term':
                require(new['scope']['request_id']==batch['request_id'], 'new item request boundary')
            if new['lifecycle']['state'] == 'active':
                require(new['verification']['confirmation']['input_ref'] in cause, 'current confirmation required')
            if new['scope']['type'] == 'long_term':
                require(new['scope']['approval']['input_ref'] in cause, 'current approval required')
            if action['type'] == 'create':
                require(target['kind'] == 'none' and new['lineage']['operation'] == 'create', 'invalid create')
                for old in staged.values():
                    if old['lifecycle']['state'] in {'withdrawn','superseded'} and semantic_identity(old)==semantic_identity(new):
                        require(parse_time(src['occurred_at'])>parse_time(old['lifecycle']['changed_at']),'past input after withdrawal requires fresh confirmation')
                require(not any(semantic_identity(old)==semantic_identity(new) and old['lifecycle']['state']=='active' for old in staged.values() if old['user_id']==new['user_id']), 'duplicate claim')
            else:
                require(current is not None and current['lifecycle']['state'] in {'active','candidate'}, 'replace target state')
                require(new['scope']['type']==current['scope']['type'], 'replace scope')
                require(new['scope'].get('request_id')==current['scope'].get('request_id'), 'replace request')
                require(current['lifecycle']['state']!='active' or new['lifecycle']['state']=='active', 'active to candidate replacement')
                require(new['lineage']['operation']=='replace' and new['lineage']['source_memory_id']==target_id and new['lineage']['family_id']!=current['lineage']['family_id'], 'replace lineage')
                current['lifecycle'].update(state='superseded',changed_at=batch['issued_at']); current['version']+=1
            staged[new['id']]=new; outputs[action['action_id']]=new['id']
        elif action['type'] in {'confirm','promote','add_evidence'}:
            require(current is not None, 'missing target')
            require(src['snapshot']['content']==current['content'] and src['snapshot']['period']==current['applicability'], 'evidence payload mismatch')
            if action['type']=='confirm':
                require(current['lifecycle']['state']=='candidate', 'confirm target state')
                if src['kind']=='image_feedback':
                    require(current['claim']['key'] in src['snapshot']['selected_aspects'], 'image aspect overreach')
                current['lifecycle']['state']='active'; current['verification']['state']='confirmed'
                current['verification']['confirmation']={'input_ref':src['input_ref'],'snapshot_ref':src['snapshot_id'],'user_id':src['user_id'],'confirmed_at':src['occurred_at'],'role':'content_confirmation'}
                current['version']+=1; outputs[action['action_id']]=target_id
            elif action['type']=='promote':
                require(current['scope']['type']=='short_term' and current['lifecycle']['state']=='active' and current['verification']['state']=='confirmed', 'promote target state')
                new=copy.deepcopy(current); new_id=f"derived::{batch['batch_id']}::{action['action_id']}"
                require(new_id not in staged, 'new identity/version')
                new.update(id=new_id, version=1, created_at=batch['issued_at'])
                new['scope']={'type':'long_term','approval':{'input_ref':src['input_ref'],'snapshot_ref':src['snapshot_id'],'user_id':src['user_id'],'approved_at':src['occurred_at'],'role':'long_term_approval'}}
                new['lineage']={'operation':'promote','source_memory_id':target_id,'family_id':current['lineage']['family_id']}
                new['evidence'].extend(copy.deepcopy(action['evidence']))
                staged[new_id]=new; outputs[action['action_id']]=new_id
            else:
                require(current['lifecycle']['state']=='active', 'evidence target state')
                current['evidence'].extend(copy.deepcopy(action['evidence'])); current['version']+=1
        elif action['type'] in {'withdraw','delete'}:
            require(current is not None, 'missing target')
            family=[key for key,item in staged.items() if item['user_id']==batch['user_id'] and item['lineage']['family_id']==current['lineage']['family_id']]
            require(all(key in batch['expected_versions'] for key in family), 'family CAS incomplete')
            require(set(src['snapshot']['target_memory_ids'])==set(family), 'displayed family mismatch')
            # The synthetic authority carries the displayed target content. A real
            # UI must also bind its exact family set to the confirmation snapshot.
            require(src['snapshot']['content']==current['content'], 'displayed target mismatch')
            for key in family:
                if action['type']=='delete':
                    require(set(action['deletion_scope']) >= {'memory','promote_family','derived_snapshots','source_spans','summaries','indexes','cache'}, 'deletion scope incomplete')
                    del staged[key]
                else:
                    staged[key]['lifecycle'].update(state='withdrawn',changed_at=batch['issued_at']); staged[key]['version']+=1
            if action['type']=='delete':
                for kept in staged.values():
                    if kept['lineage']['source_memory_id'] in family:
                        require(kept['id'] in batch['expected_versions'] and batch['expected_versions'][kept['id']]==kept['version'],'redaction CAS incomplete')
                        redaction_id=f"redaction::{batch['batch_id']}::{kept['id']}"
                        kept['lineage'].update(source_memory_id=None,source_redacted=True,source_redaction_id=redaction_id)
                        kept['version']+=1
                        generated_redactions[redaction_id]={'memory_id':kept['id'],'user_id':kept['user_id'],'operation':kept['lineage']['operation'],'version':kept['version'],'at':batch['issued_at']}
        if fail_after is not None and index==fail_after:
            raise DesignError('injected storage failure')
    for item in staged.values():
        validate_memory(item, requests, evidence, parse_time(batch['issued_at']))
    validate_lineage(staged,generated_redactions)
    return staged


def event_changes(before, after, batch):
    refs=sorted({ref['snapshot_ref'] for action in batch['actions'] for ref in action['evidence']})
    changes=[]
    for key in sorted(set(before)|set(after)):
        old,new=before.get(key),after.get(key)
        if old==new: continue
        changes.append({'memory_id':key,'operation':'delete' if new is None else 'upsert',
                        'before_version':old['version'] if old else None,
                        'after_version':new['version'] if new else None,
                        'after_state':new['lifecycle']['state'] if new else None,
                        'lineage_operation':new['lineage']['operation'] if new else None,
                        'evidence_snapshot_refs':refs})
    return changes


class ReviewStore:
    """Only a synthetic graph: receipts, staging and deletion closure."""
    def __init__(self, data, memory_ids=None):
        self.requests={x['id']:copy.deepcopy(x) for x in data['requests']}
        self.evidence={x['snapshot_id']:copy.deepcopy(x) for x in data['evidence']}
        self.memories={x['id']:copy.deepcopy(x) for x in data['memories'] if memory_ids is None or x['id'] in memory_ids}
        self.profile=data['profile']['current_revision']
        self.receipts={}; self.events=[]; self.current_inputs=copy.deepcopy(data['current_inputs']); self.deleted_before=None; self.deletion_receipts={}; self.redactions=copy.deepcopy(data.get('redactions',{}))
        self.artifacts=copy.deepcopy(data.get('derived_artifacts',{}))

    def commit(self, batch, fail_after=None):
        receipt_key=(batch['user_id'],batch['batch_id']); payload=hashlib.sha256(json.dumps(batch,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if receipt_key in self.deletion_receipts:
            completion=self.deletion_receipts[receipt_key]
            require(completion['fingerprint']==payload,'idempotency conflict')
            return copy.deepcopy(completion)
        if receipt_key in self.receipts:
            old_payload,result=self.receipts[receipt_key]
            require(old_payload==payload, 'idempotency conflict')
            return copy.deepcopy(result)
        if self.deleted_before is not None:
            metadata=evidence_input(self.evidence,self.current_inputs[batch['batch_id']])
            require(parse_time(metadata['occurred_at'])>self.deleted_before,'past input after delete requires fresh confirmation')
        before=copy.deepcopy(self.memories)
        staged=stage_batch(batch,self.memories,self.evidence,self.requests,self.profile,self.current_inputs[batch['batch_id']],fail_after,self.redactions)
        changes=event_changes(before,staged,batch)
        result={'changed':{c['memory_id']:c['after_version'] for c in changes}}
        # The model reaches this boundary only after every action succeeded.
        self.memories=staged
        for item in staged.values():
            if item['lineage'].get('source_redacted') and item['lineage']['source_redaction_id'] not in self.redactions:
                self.redactions[item['lineage']['source_redaction_id']]={'memory_id':item['id'],'user_id':item['user_id'],'operation':item['lineage']['operation'],'version':item['version'],'at':batch['issued_at']}
        deleted={key for key in before if key not in staged}
        if deleted:
            roots=set(deleted)
            for key in deleted:
                roots.update(ref['snapshot_ref'] for ref in before[key]['evidence'])
                if before[key]['verification']['confirmation']: roots.add(before[key]['verification']['confirmation']['snapshot_ref'])
                if before[key]['scope']['type']=='long_term': roots.add(before[key]['scope']['approval']['snapshot_ref'])
            surviving_refs={ref['snapshot_ref'] for item in staged.values() for ref in item['evidence']}
            for ref in roots-surviving_refs: self.evidence.pop(ref,None)
            removed=set(roots)
            while True:
                extra={key for key,value in self.artifacts.items() if set(value['sources'])&removed}
                if extra<=removed: break
                removed|=extra
            for key in removed: self.artifacts.pop(key,None)
            self.receipts={key:value for key,value in self.receipts.items() if not (set(value[1]['changed'])&deleted)}
            self.events=[event for event in self.events if isinstance(event,list) and not any(change['memory_id'] in deleted for change in event)]
            self.redactions={key:proof for key,proof in self.redactions.items() if proof['memory_id'] not in deleted}
            self.deleted_before=parse_time(batch['issued_at'])
        if any(before.get(k,{}).get('scope',{}).get('type')=='long_term' or staged.get(k,{}).get('scope',{}).get('type')=='long_term' for k in result['changed']): self.profile+=1
        if batch['request_id'] is not None and any(before.get(k,{}).get('scope',{}).get('type')=='short_term' or staged.get(k,{}).get('scope',{}).get('type')=='short_term' for k in result['changed']): self.requests[batch['request_id']]['revision']+=1
        if deleted:
            self.events.append({'deleted':True})
            completion={'contract_type':'deletion_receipt','schema_version':'0.2','token':f"delete::{batch['batch_id']}",'fingerprint':payload,'completed_at':batch['issued_at'],'expires_at':(parse_time(batch['issued_at'])+timedelta(hours=24)).isoformat()}
            schema_check(load_schema_validator(DEFAULT_SCHEMA),completion,'generated deletion receipt')
            self.deletion_receipts[receipt_key]=copy.deepcopy(completion)
            return completion
        self.events.append(changes); self.receipts[receipt_key]=(payload,copy.deepcopy(result))
        return result


def interpret_snapshot(source, wanted_scope, origin='current'):
    """Evaluate trusted confirmation roles; never parse natural language."""
    if origin!='current': return {'status':'no_change','scope':None,'question':False}
    roles=set(source['snapshot']['authorized_roles'])
    if 'content_confirmation' not in roles:
        return {'status':'needs_clarification','scope':None,'question':True}
    if wanted_scope=='long_term' and 'long_term_approval' not in roles:
        return {'status':'needs_clarification','scope':None,'question':True}
    return {'status':'ready','scope':wanted_scope,'question':False}


def study_context(records, namespace, request_id, mode):
    eligible=[r for r in records if r['namespace']==namespace and r['confirmed']]
    if mode=='split': eligible=[r for r in eligible if r['scope']=='long_term' or r['request_id']==request_id]
    require(mode in {'split','unified'}, 'unknown study adapter')
    winners={}
    for record in sorted(eligible,key=lambda r:(r['sequence'],r['id'])): winners[record['key']]=record
    return [record['id'] for _,record in sorted(winners.items())]


def set_path(value,path,new):
    target=value
    for part in path[:-1]: target=target[part]
    target[path[-1]]=copy.deepcopy(new)


def evaluate_scenario(inputs,data):
    store=ReviewStore(data,inputs.get('memory_ids'))
    for mutation in inputs.get('mutations',[]): set_path(store.__dict__,mutation['path'],mutation['value'])
    kind=inputs['kind']
    if kind=='sequence':
        errors=[]
        for step in inputs['steps']:
            batch=copy.deepcopy(next(b for b in data['batches']+data.get('batch_templates',[]) if b['batch_id']==step['batch_id']))
            for mutation in step.get('store_mutations',[]): set_path(store.__dict__,mutation['path'],mutation['value'])
            for mutation in step.get('batch_mutations',[]): set_path(batch,mutation['path'],mutation['value'])
            try: store.commit(batch)
            except DesignError as exc: errors.append(str(exc))
        return {'memory_ids':sorted(store.memories),'errors':errors,'receipt_count':len(store.receipts),'deleted_boundary':store.deleted_before is not None}
    if kind=='context':
        query=copy.deepcopy(data['queries']['ctx_demo']); query.update(inputs.get('query',{}))
        result=retrieve(list(store.memories.values()),store.evidence,store.requests[inputs['request_id']],query,parse_time(inputs['now']))
        return {'used':[x['id'] for x,_ in result['selected']], 'excluded':{x['memory_id']:x['reason'] for x in result['excluded']},
                'overridden':result['overridden'],'unresolved':sorted(result['unresolved']),'truncated':result['truncated']}
    if kind=='identity':
        left=store.memories[inputs['left_id']]; right=copy.deepcopy(store.memories[inputs['right_id']])
        for mutation in inputs['right_mutations']: set_path(right,mutation['path'],mutation['value'])
        return {'same':semantic_identity(left)==semantic_identity(right)}
    if kind=='today':
        current=parse_time(inputs['occurred_at']).astimezone(ZoneInfo(inputs['timezone']))
        start=current.replace(hour=0,minute=0,second=0,microsecond=0)
        end=start+timedelta(days=1)
        return {'from':start.astimezone(timezone.utc).isoformat(),'until':end.astimezone(timezone.utc).isoformat()}
    if kind=='interpret': return interpret_snapshot(store.evidence[inputs['snapshot_ref']],inputs['wanted_scope'],inputs.get('origin','current'))
    if kind=='batch':
        batch=copy.deepcopy(next(b for b in data['batches']+data.get('batch_templates',[]) if b['batch_id']==inputs['batch_id']))
        for mutation in inputs.get('batch_mutations',[]): set_path(batch,mutation['path'],mutation['value'])
        before=copy.deepcopy((store.memories,store.evidence,store.artifacts,store.events,store.receipts))
        try:
            first=store.commit(batch,inputs.get('fail_after'))
            if inputs.get('replay'):
                again=copy.deepcopy(batch)
                for mutation in inputs.get('replay_mutations',[]): set_path(again,mutation['path'],mutation['value'])
                try:
                    second=store.commit(again)
                    return {'replayed':second==first,'event_count':len(store.events),'changed':first.get('changed',{})}
                except DesignError as exc:
                    return {'error':str(exc),'event_count':len(store.events),'changed':first.get('changed',{})}
            actual_changes=event_changes(before[0],store.memories,batch)
            return {'changed':{change['memory_id']:change['after_version'] for change in actual_changes},'states':{k:store.memories[k]['lifecycle']['state'] for k in inputs.get('observe_ids',[]) if k in store.memories},
                    'absent':sorted(k for k in inputs.get('observe_absent',[]) if k not in store.memories),
                    'artifacts':sorted(store.artifacts),'evidence_absent':sorted(k for k in inputs.get('observe_evidence_absent',[]) if k not in store.evidence)}
        except DesignError as exc:
            return {'error':str(exc),'rolled_back':before==(store.memories,store.evidence,store.artifacts,store.events,store.receipts)}
    if kind=='request':
        req=store.requests[inputs['request_id']]
        if req['user_id']!=inputs['user_id']: return {'error':'request owner'}
        now=parse_time(inputs['now'])
        if now>=parse_time(req['retention_until']): return {'error':'request expired'}
        action=inputs['action']
        if action=='resume':
            require(inputs['confirmed'], 'resume confirmation required')
            req['status']='open'; req['revision']+=1
            return {'id':req['id'],'status':req['status'],'revision':req['revision']}
        if action=='clone':
            require(inputs['confirmed'], 'clone confirmation required')
            require(inputs['new_id'] not in store.requests,'clone requires new ID')
            chosen=inputs['selected_ids']
            require(all(store.memories[k]['scope'].get('request_id')==req['id'] for k in chosen), 'clone source request')
            return {'id':inputs['new_id'],'source_ids':chosen,'copied_approval':False}
        if action in {'close','cancel'}:
            req['status']='closed' if action=='close' else 'cancelled'; req['revision']+=1
            return {'id':req['id'],'status':req['status'],'revision':req['revision']}
        raise DesignError('unknown request action')
    if kind=='study':
        return {'used':study_context(data['study_records'],inputs['namespace'],inputs['request_id'],inputs['mode'])}
    if kind=='choice':
        selected=inputs['selected_ids'] if inputs['confirmed'] and not inputs['closed'] else []
        return {'selected':selected,'long_term_write':bool(selected)}
    if kind=='claim': return {'conflict':claims_conflict(inputs['left'],inputs['right'])}
    if kind=='retention':
        req=store.requests[inputs['request_id']]
        return {'until':min(parse_time(req['last_activity_at'])+timedelta(days=30),parse_time(req['created_at'])+timedelta(days=90)).isoformat()}
    raise DesignError(f'unknown scenario kind: {kind}')


def unique_registry(items,key):
    result={item[key]:item for item in items}
    require(len(result)==len(items),f'duplicate {key}')
    return result


def validate_contracts(data,schema_path):
    validator=load_schema_validator(schema_path)
    contracts=[data['retention_policy']]
    for name in ('evidence','requests','memories','contexts','decisions','batches','events','results','deletion_receipts','batch_templates'):
        require(data[name],f'missing {name}'); contracts.extend(data[name])
    for receipt in data['deletion_receipts']:
        require(parse_time(receipt['expires_at'])==parse_time(receipt['completed_at'])+timedelta(hours=24),'delete receipt retention')
    for contract in contracts: schema_check(validator,contract,contract['contract_type'])
    evidence=unique_registry(data['evidence'],'snapshot_id'); requests=unique_registry(data['requests'],'id'); memories=unique_registry(data['memories'],'id')
    contexts=unique_registry(data['contexts'],'context_id'); batches=unique_registry(data['batches'],'batch_id')
    events=unique_registry(data['events'],'event_id'); results=unique_registry(data['results'],'result_id')
    for req in requests.values(): validate_request(req)
    for src in evidence.values():
        validate_evidence(src)
        require(src['request_id'] in requests and requests[src['request_id']]['user_id']==src['user_id'],'evidence request owner')
        require(src['raw_retention_until']==requests[src['request_id']]['retention_until'],'raw retention mismatch')
    for item in memories.values(): validate_memory(item,requests,evidence,parse_time(data['now']))
    validate_lineage(memories,data.get('redactions',{}))
    profile=data['profile']['current_revision']
    require(all(ctx['user_id']==data['profile']['user_id'] for ctx in contexts.values()), 'profile owner')
    for context in contexts.values():
        require(context['user_id']==requests[context['request_id']]['user_id'],'context owner')
        validate_context(context,memories,evidence,requests,data['queries'],profile)
    snapshots={c['context_snapshot_id']:c for c in contexts.values()}
    for decision in data['decisions']:
        require(decision['context_snapshot_id'] in snapshots,'decision context')
        ctx=snapshots[decision['context_snapshot_id']]
        require(decision['request_revision']==ctx['request_revision'] and decision['profile_revision']==ctx['profile_revision'],'decision revision')
        source=evidence_input(evidence,decision['source_input_ref'])
        require(source['user_id']==ctx['user_id'] and source['request_id']==ctx['request_id'],'decision input owner')
        require((decision['status']=='ready')==bool(decision['proposals']) or decision['status']=='needs_clarification','decision proposal shape')
        for proposal in decision['proposals']:
            require(proposal['target_memory_id'] is None or (proposal['target_memory_id'] in memories and memories[proposal['target_memory_id']]['user_id']==ctx['user_id']),'decision target owner')
            for ref in proposal['evidence']:
                approved=checked_ref(ref,evidence,ctx['user_id'],request_id=ctx['request_id'])
                if proposal['claim'] is not None:
                    require(proposal['claim']==approved['snapshot']['claim'],'proposal claim snapshot mismatch')
                require(ref['input_ref']==decision['source_input_ref'],'decision current evidence')
    staged_by_id={}
    for batch in batches.values():
        require(batch['context_snapshot_id'] in snapshots,'batch context')
        ctx=snapshots[batch['context_snapshot_id']]
        require(ctx['user_id']==batch['user_id'],'batch context owner')
        require(batch['request_id'] is None or ctx['request_id']==batch['request_id'],'batch context request')
        staged_by_id[batch['batch_id']]=stage_batch(batch,memories,evidence,requests,profile,data['current_inputs'][batch['batch_id']],redactions=data.get('redactions',{}))
    for event in events.values():
        batch=batches.get(event['batch_id'])
        require(batch is not None and event['user_id']==batch['user_id'] and event['request_id']==batch['request_id'],'event batch owner')
        expected=event_changes(memories,staged_by_id[batch['batch_id']],batch)
        require(sorted(event['changes'],key=lambda c:c['memory_id'])==expected,'event committed changes')
        require(sorted(event['change_ids'])==sorted(c['memory_id'] for c in expected),'event change ids')
    for result in results.values():
        require(result['batch_id'] in batches and result['user_id']==batches[result['batch_id']]['user_id'],'result batch owner')
        if result['status']=='accepted':
            event=events.get(result['event_id'])
            require(event is not None and event['batch_id']==result['batch_id'],'result event')
            require(result['versions']=={c['memory_id']:c['after_version'] for c in event['changes'] if c['after_version'] is not None},'result committed versions')
    return len(contracts)


def validate(data,schema_path):
    count=validate_contracts(data,schema_path)
    require(data['schema_version']==VERSION,'fixture version')
    categories=set(); ids=set()
    for case in data['cases']:
        require(case['case_id'] not in ids,'duplicate case id'); ids.add(case['case_id']); categories.update(case['covers'])
        actual=evaluate_scenario(case['input'],data)
        require(actual==case['expected'],f"scenario {case['case_id']} expected {case['expected']!r}, got {actual!r}")
    require({f'C{i:02d}' for i in range(1,14)}<=categories,'required C01–C13 coverage')
    for negative in data['negative_fixtures']:
        changed=copy.deepcopy(data)
        for mutation in negative['mutations']: set_path(changed,mutation['path'],mutation['value'])
        try:
            validate_contracts(changed,schema_path)
        except (DesignError, KeyError, TypeError) as exc:
            require(negative['diagnostic'] in str(exc),f"negative {negative['id']} wrong diagnostic: {exc}")
        else: raise DesignError(f"negative accepted: {negative['id']}")
    return {'contracts':count,'scenarios':len(data['cases']),'rejected_mutations':len(data['negative_fixtures'])}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',type=Path,default=DEFAULT_SCHEMA)
    parser.add_argument('--cases',type=Path,default=DEFAULT_CASES)
    args=parser.parse_args(argv)
    try:
        summary=validate(json.loads(args.cases.read_text()),args.schema)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'memory design validation failed: {exc}',file=sys.stderr); return 1
    print(f'Accepted v0.2 memory design: PASS (Draft202012+FormatChecker); {summary}')
    print('Scope: synthetic trusted evidence and in-memory policy model; no LLM, DB, authentication, or filesystem purge.')
    return 0


if __name__=='__main__': raise SystemExit(main())
