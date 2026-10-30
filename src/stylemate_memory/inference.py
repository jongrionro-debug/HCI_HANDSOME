"""Read-only target inference for legacy consumer and opt-in lumi-memory-v1.

Gateways propose soft interpretations. Code owns vocabulary, target scope,
confirmed constraints, complete target fields and freshness validation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Protocol

from . import contracts as c
from .errors import StyleMateError
from .model_io import validate_proposal_v1
from .registry import FEATURES, REGISTRY_VERSION, category_for_garment_type, validate_values


SUGGESTION_FIELDS = {"target_id", "feature", "values", "match", "source_ids", "reason"}
_MULTI_FEATURES = {"style", "mood", "season", "functions"}


class ModelAdapter(Protocol):
    """Minimal read-only model boundary.

    The adapter must not write memory.  It receives the already-filtered
    context and returns only the exact suggestion shape documented here.
    """

    def propose(self, context: dict[str, Any]) -> dict[str, Any]:
        ...


class RuleAdapter:
    """A deterministic, offline adapter used for demos and contract tests.

    It deliberately emits no value merely because an item has 17 empty
    attributes.  A small set of exact, already-confirmed goal phrases can
    produce a soft suggestion when a source memory is available.  This is a
    wiring fixture, not a claim about model quality.
    """

    VERSION = "rule-v1"

    def propose(self, context: dict[str, Any]) -> dict[str, Any]:
        suggestions: list[dict[str, Any]] = []
        facts = context.get("facts") or {}
        goal = facts.get("goal")
        goal_sources = [
            source_id
            for fact in context.get("fact_sources", [])
            if isinstance(fact, dict) and fact.get("fact") == "goal" and not fact.get("conflict")
            for source_id in fact.get("source_ids", [])
            if isinstance(source_id, str) and source_id
        ]
        if goal_sources:
            for target_id, source_id, scoped_goal in _goal_target_sources(context):
                text = scoped_goal.casefold() if isinstance(scoped_goal, str) else ""
                if text == "business casual":
                    suggestions.append({
                        "target_id": target_id,
                        "feature": "formality",
                        "values": [4],
                        "match": "any",
                        "source_ids": [source_id],
                        "reason": "확인된 목표의 business casual 표현에서 제안",
                    })
                elif text in {"smart casual", "단정"}:
                    suggestions.append({
                        "target_id": target_id,
                        "feature": "formality",
                        "values": [3],
                        "match": "any",
                        "source_ids": [source_id],
                        "reason": "확인된 목표의 smart casual 표현에서 제안",
                    })
                elif text in {"formal", "정장"}:
                    suggestions.append({
                        "target_id": target_id,
                        "feature": "formality",
                        "values": [5],
                        "match": "any",
                        "source_ids": [source_id],
                        "reason": "확인된 목표의 formal 표현에서 제안",
                    })
                elif text in {"casual", "편한"}:
                    suggestions.append({
                        "target_id": target_id,
                        "feature": "formality",
                        "values": [2],
                        "match": "any",
                        "source_ids": [source_id],
                        "reason": "확인된 목표의 casual 표현에서 제안",
                    })
        return {"suggestions": suggestions, "questions": []}


def _fact_scope_matches(scope: Any, target: dict[str, Any]) -> bool:
    if scope in (None, "global"):
        return True
    if not isinstance(scope, dict):
        return False
    target_id = scope.get("slot_id", scope.get("target_id"))
    if target_id is not None and target_id != target.get("target_id"):
        return False
    garment_type = scope.get("garment_type")
    if garment_type is not None and garment_type != target.get("garment_type"):
        return False
    return all(key in {"level", "slot_id", "target_id", "garment_type", "category"} for key in scope)


def _goal_target_sources(context: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Return one scoped goal evidence ID for each applicable target."""

    goal_sources = [
        fact
        for fact in context.get("fact_sources", [])
        if isinstance(fact, dict) and fact.get("fact") == "goal" and not fact.get("conflict")
    ]
    result: list[tuple[str, str, Any]] = []
    for target in context.get("targets", []):
        for fact in goal_sources:
            source_ids = [source_id for source_id in fact.get("source_ids", []) if isinstance(source_id, str) and source_id]
            if source_ids and _fact_scope_matches(fact.get("target_scope"), target):
                result.append((target["target_id"], source_ids[0], fact.get("value")))
                break
    return result


def _target_map(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for target in context.get("targets", []):
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or target_id in result:
            raise StyleMateError("invalid_context", "context target id가 유효하지 않습니다")
        result[target_id] = target
    if not result:
        raise StyleMateError("invalid_context", "context에 target이 없습니다")
    return result


def _current_source_ids(context: dict[str, Any]) -> set[str]:
    ids = {memory.get("id") for memory in context.get("memories", []) if isinstance(memory.get("id"), str)}
    for binding in context.get("bindings", []):
        ids.update(source_id for source_id in binding.get("source_ids", []) if isinstance(source_id, str))
    for fact in context.get("fact_sources", []):
        if isinstance(fact, dict) and not fact.get("conflict"):
            ids.update(source_id for source_id in fact.get("source_ids", []) if isinstance(source_id, str))
    return ids


def _source_applies_to_target(context: dict[str, Any], source_id: str, target_id: str) -> bool:
    """Ensure a model cannot reuse a memory selected for a different slot."""

    for fact in context.get("fact_sources", []):
        if not isinstance(fact, dict) or fact.get("conflict") or source_id not in (fact.get("source_ids") or []):
            continue
        target = next((item for item in context.get("targets", []) if item.get("target_id") == target_id), None)
        return target is not None and _fact_scope_matches(fact.get("target_scope"), target)
    matched_binding = False
    for binding in context.get("bindings", []):
        if source_id not in (binding.get("source_ids") or []):
            continue
        matched_binding = True
        if binding.get("target_id") == target_id:
            return True
    # A source that is visible only as explanatory memory but has no binding is
    # not a usable target reference.  This fails closed for future schema keys.
    return not matched_binding and False


def _context_constraints(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [binding for binding in context.get("bindings", []) if isinstance(binding, dict)]


def _validate_suggestion(suggestion: Any, context: dict[str, Any], target_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(suggestion, dict) or set(suggestion) != SUGGESTION_FIELDS:
        raise StyleMateError("invalid_model_proposal", "모델 suggestion은 정해진 6개 field만 가져야 합니다")
    target_id = suggestion.get("target_id")
    feature = suggestion.get("feature")
    if target_id not in target_map:
        raise StyleMateError("invalid_model_proposal", "모델이 알 수 없는 target을 제안했습니다")
    if feature not in FEATURES:
        raise StyleMateError("invalid_model_proposal", "모델이 지원하지 않는 feature를 제안했습니다")
    target = target_map[target_id]
    category = category_for_garment_type(target.get("garment_type"))
    applicable = FEATURES[feature]["applicable_categories"]
    if category not in applicable and "All" not in applicable:
        raise StyleMateError("invalid_model_proposal", f"{feature}은 {target.get('garment_type')}에 적용되지 않습니다")
    values = suggestion.get("values")
    match = suggestion.get("match")
    if feature == "garment_type" and values != [target.get("garment_type")]:
        raise StyleMateError("invalid_model_proposal", "garment_type은 target 선언과 바꿀 수 없습니다")
    try:
        validate_values(feature, values, match=match, garment_type=target.get("garment_type"))
    except StyleMateError as error:
        raise StyleMateError("invalid_model_proposal", error.message) from error
    source_ids = suggestion.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids or any(not isinstance(source_id, str) for source_id in source_ids):
        raise StyleMateError("invalid_model_proposal", "모델 suggestion의 source_ids가 필요합니다")
    current_ids = _current_source_ids(context)
    if any(source_id not in current_ids for source_id in source_ids):
        raise StyleMateError("invalid_model_proposal", "모델 suggestion이 현재 context 밖의 source를 참조했습니다")
    if any(not _source_applies_to_target(context, source_id, target_id) for source_id in source_ids):
        raise StyleMateError("invalid_model_proposal", "모델 suggestion이 다른 target의 memory를 참조했습니다")
    if any(
        isinstance(question, dict)
        and question.get("target_id") == target_id
        and question.get("feature") == feature
        and question.get("reason") in {"same_priority_conflict", "hard_constraint_conflict"}
        for question in context.get("questions", [])
    ):
        raise StyleMateError("model_constraint_violation", "충돌 중인 feature는 모델 제안으로 해결할 수 없습니다")
    if not isinstance(suggestion.get("reason"), str) or not suggestion["reason"].strip():
        raise StyleMateError("invalid_model_proposal", "모델 suggestion의 reason이 필요합니다")
    return deepcopy(suggestion)


def _check_constraints(suggestion: dict[str, Any], context: dict[str, Any]) -> None:
    """Reject a model response that rewrites an explicit user constraint."""

    for binding in _context_constraints(context):
        if binding.get("target_id") != suggestion["target_id"] or binding.get("feature") != suggestion["feature"]:
            continue
        binding_values = set(binding.get("values") or [])
        suggestion_values = set(suggestion.get("values") or [])
        polarity = binding.get("polarity")
        if binding.get("match", "any") != suggestion.get("match"):
            raise StyleMateError("model_constraint_violation", "모델이 사용자의 match 연산을 바꾸었습니다")
        if polarity == "avoid" and binding_values & suggestion_values:
            raise StyleMateError("model_constraint_violation", "모델이 사용자의 avoid 조건을 제안했습니다")
        if polarity == "require" and binding_values != suggestion_values:
            raise StyleMateError("model_constraint_violation", "모델이 사용자의 require 조건을 바꾸었습니다")
        if polarity == "prefer" and binding.get("feature") not in _MULTI_FEATURES and binding_values != suggestion_values:
            raise StyleMateError("model_constraint_violation", "모델이 사용자의 직접 조건을 바꾸었습니다")


def _read_proposal(raw: Any, context: dict[str, Any], target_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw, dict) or set(raw) - {"suggestions", "questions"}:
        raise StyleMateError("invalid_model_proposal", "모델 proposal의 top-level field가 유효하지 않습니다")
    suggestions = raw.get("suggestions", [])
    questions = raw.get("questions", [])
    if not isinstance(suggestions, list) or not isinstance(questions, list) or any(not isinstance(q, str) or not q.strip() for q in questions):
        raise StyleMateError("invalid_model_proposal", "모델 proposal의 suggestions/questions 형식이 잘못되었습니다")
    checked: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    by_feature: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw_suggestion in suggestions:
        suggestion = _validate_suggestion(raw_suggestion, context, target_map)
        _check_constraints(suggestion, context)
        key = (suggestion["target_id"], suggestion["feature"], repr((suggestion["values"], suggestion["match"])))
        if key in seen:
            continue
        feature_key = (suggestion["target_id"], suggestion["feature"])
        prior = by_feature.setdefault(feature_key, [])
        if prior:
            if suggestion["feature"] not in _MULTI_FEATURES:
                raise StyleMateError("model_conflict", "모델이 같은 target/feature에 충돌하는 값을 여러 개 제안했습니다")
            if any(item["match"] != suggestion["match"] for item in prior):
                raise StyleMateError("model_conflict", "다중 feature의 match 연산이 일관되지 않습니다")
        checked.append(suggestion)
        seen.add(key)
        prior.append(suggestion)
    return checked, list(questions)


def _direct_suggestions(context: dict[str, Any], target_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    suggestions: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for binding in _context_constraints(context):
        target_id = binding.get("target_id")
        feature = binding.get("feature")
        if target_id not in target_map or feature not in FEATURES:
            continue
        constraints.append(deepcopy(binding))
        if binding.get("polarity") not in {"prefer", "require"}:
            continue
        values = deepcopy(binding.get("values") or [])
        key = (target_id, feature, repr(values), binding.get("match", "any"))
        if key in seen:
            continue
        seen.add(key)
        suggestions.append({
            "target_id": target_id,
            "feature": feature,
            "values": values,
            "match": binding.get("match", "any"),
            "source_ids": [source_id for source_id in binding.get("source_ids", []) if source_id],
            "reason": "사용자가 확인한 직접 조건",
        })
    return suggestions, constraints


def _feature_applicable(feature: str, target: dict[str, Any]) -> bool:
    category = category_for_garment_type(target.get("garment_type"))
    applicable = FEATURES[feature]["applicable_categories"]
    return category in applicable or "All" in applicable


def _make_profile(
    context: dict[str, Any],
    suggestions: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    questions: list[str],
) -> dict[str, Any]:
    target_map = _target_map(context)
    suggestions_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for suggestion in suggestions:
        suggestions_by_target.setdefault((suggestion["target_id"], suggestion["feature"]), []).append(suggestion)
    constraints_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for binding in constraints:
        constraints_by_target.setdefault((binding["target_id"], binding["feature"]), []).append(binding)

    profile_targets: list[dict[str, Any]] = []
    context_conflicts = {(q.get("target_id"), q.get("feature")) for q in context.get("questions", []) if isinstance(q, dict) and q.get("reason") in {"same_priority_conflict", "hard_constraint_conflict"}}
    for target_id, target in target_map.items():
        feature_profile: dict[str, Any] = {}
        for feature in FEATURES:
            key = (target_id, feature)
            if feature == "garment_type":
                feature_profile[feature] = {
                    "status": "specified",
                    "values": [target["garment_type"]],
                    "match": "any",
                    "source_ids": [],
                    "origin": "target",
                }
                continue
            if not _feature_applicable(feature, target):
                feature_profile[feature] = {"status": "not_applicable", "values": [], "match": "any", "source_ids": []}
                continue
            if key in context_conflicts:
                feature_profile[feature] = {"status": "conflict", "values": [], "match": "any", "source_ids": []}
                continue
            feature_suggestions = suggestions_by_target.get(key, [])
            bindings = constraints_by_target.get(key, [])
            if feature_suggestions:
                direct = any(
                    binding.get("polarity") in {"prefer", "require"}
                    and binding.get("source_ids")
                    and set(binding.get("source_ids", [])) & {
                        source_id for suggestion in feature_suggestions for source_id in suggestion.get("source_ids", [])
                    }
                    for binding in bindings
                )
                values: list[str | int] = []
                source_ids: list[str] = []
                for suggestion in feature_suggestions:
                    for value in suggestion["values"]:
                        if value not in values:
                            values.append(value)
                    for source_id in suggestion["source_ids"]:
                        if source_id not in source_ids:
                            source_ids.append(source_id)
                flat_match = feature_suggestions[0]["match"] if len({suggestion["match"] for suggestion in feature_suggestions}) == 1 else None
                feature_profile[feature] = {
                    "status": "specified" if direct else "inferred",
                    "values": values,
                    # A mixed multi-label match cannot be represented by one
                    # flat operator; callers must use the per-suggestion
                    # entries and constraints below.
                    "match": flat_match,
                    "source_ids": source_ids,
                    "reason": feature_suggestions[0]["reason"],
                    "suggestions": deepcopy(feature_suggestions),
                    "constraints": deepcopy(bindings),
                    "origin": "explicit" if direct else "inferred",
                }
            elif bindings:
                # Avoid-only constraints have no positive target value but are
                # still visible to callers as a constrained, unresolved field.
                positives = [binding for binding in bindings if binding.get("polarity") in {"prefer", "require"}]
                if positives:
                    first = positives[0]
                    feature_profile[feature] = {
                        "status": "specified",
                        "values": deepcopy(first.get("values", [])),
                        "match": first.get("match", "any"),
                        "source_ids": deepcopy(first.get("source_ids", [])),
                        "origin": "explicit",
                    }
                else:
                    feature_profile[feature] = {
                        "status": "unspecified",
                        "values": [],
                        "match": "any",
                        "source_ids": [],
                        "constraints": deepcopy(bindings),
                    }
            else:
                feature_profile[feature] = {"status": "unspecified", "values": [], "match": "any", "source_ids": []}
        profile_targets.append({"target_id": target_id, "garment_type": target["garment_type"], "features": feature_profile})

    return {
        "context_id": context.get("context_id"),
        "context_hash": context.get("context_hash"),
        "registry_version": REGISTRY_VERSION,
        "targets": profile_targets,
        "suggestions": suggestions,
        "constraints": constraints,
        "questions": questions,
        "blocked": bool(context.get("blocked")),
        "inference": {"adapter": None, "adapter_version": None, "source_ids": sorted(_current_source_ids(context))},
    }


def infer(context: dict[str, Any], adapter: ModelAdapter) -> dict[str, Any]:
    """Validate an adapter proposal and return a complete target profile.

    Direct bindings are merged after adapter validation, so an omitted model
    field cannot erase a user's explicit requirement or avoidance.  This
    function does not persist the result as memory.
    """

    if not isinstance(context, dict):
        raise StyleMateError("invalid_context", "context는 object여야 합니다")
    if context.get("registry_version") != REGISTRY_VERSION:
        raise StyleMateError("registry_mismatch", "context의 registry version이 현재 사전과 다릅니다")
    if not hasattr(adapter, "propose"):
        raise StyleMateError("invalid_adapter", "adapter.propose가 필요합니다")
    target_map = _target_map(context)
    direct, constraints = _direct_suggestions(context, target_map)
    questions: list[str] = []
    for question in context.get("questions", []):
        if isinstance(question, str):
            questions.append(question)
        elif isinstance(question, dict):
            reason = question.get("message") or question.get("reason")
            if isinstance(reason, str):
                questions.append(reason)

    if context.get("blocked"):
        raise StyleMateError("context_blocked", "전달 가능한 context 예산이 부족해 LLM 추론을 보류했습니다.")
    else:
        raw = adapter.propose(deepcopy(context))
        model_suggestions, model_questions = _read_proposal(raw, context, target_map)
        questions.extend(model_questions)
        adapter_version = getattr(adapter, "VERSION", adapter.__class__.__name__)
        adapter_name = adapter.__class__.__name__

    # The model is allowed to add soft prefer suggestions, but never to replace
    # a direct one.  A duplicate direct suggestion is simply de-duplicated.
    merged = list(direct)
    existing = {(s["target_id"], s["feature"], repr((s["values"], s["match"]))) for s in merged}
    for suggestion in model_suggestions:
        key = (suggestion["target_id"], suggestion["feature"], repr((suggestion["values"], suggestion["match"])))
        if key not in existing:
            merged.append(suggestion)
            existing.add(key)
    profile = _make_profile(context, merged, constraints, questions)
    profile["inference"]["adapter"] = adapter_name
    profile["inference"]["adapter_version"] = adapter_version
    return profile


def _v1_fail(code: str = "invalid_input") -> None:
    messages = {
        "invalid_input": "목표 생성의 대상·제약·근거·버전 연결이 유효하지 않습니다.",
        "invalid_output": "모델 목표 제안이 근거나 직접 제약을 벗어났습니다.",
        "stale_context": "요청·기억·사전·색인 또는 유효 기간이 달라져 목표를 다시 만들어야 합니다.",
        "context_blocked": "필수 근거를 확보하거나 상충을 확인할 때까지 목표 생성을 보류합니다.",
    }
    raise StyleMateError(code, messages[code])


def _v1_text(value: Any, limit: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _v1_refs(refs: Any) -> list[c.ObjectRef]:
    if not isinstance(refs, list):
        _v1_fail()
    versions: dict[tuple[str, str], int] = {}
    for ref in refs:
        c.validate_ref(ref)
        key = (ref["type"], ref["id"])
        if key in versions and versions[key] != ref["version"]:
            _v1_fail()
        versions[key] = ref["version"]
    return [{"type": kind, "id": identifier, "version": version}
            for (kind, identifier), version in sorted(versions.items())]


def _v1_time(value: Any) -> datetime:
    if not isinstance(value, str):
        _v1_fail()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
    except ValueError:
        _v1_fail()
    return result


def _v1_basis(basis: Any, registry: c.RegistryPort) -> c.Basis:
    if not isinstance(basis, dict) or set(basis) != c.Basis.__required_keys__:
        _v1_fail()
    if (basis["contract_version"] != c.CONTRACT_VERSION
            or basis["registry_version"] != registry.version or registry.version != c.V1_REGISTRY_VERSION):
        raise StyleMateError("unsupported_contract", "목표 생성에는 명시적인 v1 계약과 Park 사전이 필요합니다.")
    if (not _v1_text(basis["request_id"])
            or any(type(basis[key]) is not int or basis[key] < minimum
                   for key, minimum in (("request_revision", 1), ("profile_revision", 0)))
            or basis["index_version"] is not None and not _v1_text(basis["index_version"], 256)):
        _v1_fail()
    result = deepcopy(basis)
    result["object_versions"] = _v1_refs(basis["object_versions"])
    if basis["valid_until"] is not None:
        _v1_time(basis["valid_until"])
    # C2 has no catalog dependency. A may attach one after product search;
    # freshness then compares that complete dependency as well.
    if basis["catalog"] is not None and not isinstance(basis["catalog"], dict):
        _v1_fail()
    return result


def _v1_path(spec: c.BindingSpec) -> tuple[str, ...]:
    return (("PI", spec["feature"]) if spec["domain"] == "PI" else
            ("FEA", spec["category"], spec["subcategory"], spec["tag"]))


def _v1_matches(selector: Any, target: c.TargetSpec) -> bool:
    return (isinstance(selector, dict) and set(selector) == {"garment_type", "slot_id"}
            and selector["garment_type"] in (None, target["garment_type"])
            and selector["slot_id"] in (None, target["target_id"]))


def _v1_context(context: c.MemoryContext, registry: c.RegistryPort) -> None:
    """Check the C2 boundary; eligibility/confirmation proofs remain C2's job."""
    if not isinstance(context, dict) or set(context) != c.MemoryContext.__required_keys__:
        _v1_fail()
    basis = _v1_basis(context["basis"], registry)
    if (not _v1_text(context["context_id"]) or type(context["blocked"]) is not bool
            or context["retrieval_status"] not in ("complete", "partial", "unavailable")
            or not isinstance(context["questions"], list)
            or any(not _v1_text(q, 16000) for q in context["questions"])):
        _v1_fail()
    if context["blocked"] or context["retrieval_status"] == "unavailable":
        _v1_fail("context_blocked")
    inputs = context["model_input"]
    if (not isinstance(inputs, dict) or set(inputs) != c.ProposalInput.__required_keys__
            or not isinstance(inputs["registry"], dict)
            or inputs["registry"].get("version") != registry.version
            or not isinstance(inputs["targets"], list) or not inputs["targets"]
            or not isinstance(inputs["sources"], list) or not inputs["sources"]
            or not isinstance(context["source_refs"], dict)):
        _v1_fail()
    targets: dict[str, c.TargetSpec] = {}
    for target in inputs["targets"]:
        if (not isinstance(target, dict) or set(target) != c.TargetSpec.__required_keys__
                or any(not _v1_text(v) for v in target.values()) or target["target_id"] in targets):
            _v1_fail()
        targets[target["target_id"]] = target
    for alias, bundle in context["source_refs"].items():
        if (not _v1_text(alias) or not _v1_refs(bundle)
                or any(ref not in basis["object_versions"] for ref in bundle)):
            _v1_fail()
    sources = {}
    for source in inputs["sources"]:
        if (not isinstance(source, dict) or set(source) != c.ModelSource.__required_keys__
                or not _v1_text(source["source_id"]) or not _v1_text(source["content"], 4000)
                or source["kind"] not in ("memory", "user_text", "image_selection")
                or source["source_id"] in sources or source["source_id"] not in context["source_refs"]
                or not any(_v1_matches(source["selector"], t) for t in targets.values())):
            _v1_fail()
        bundle = context["source_refs"][source["source_id"]]
        required = {"evidence", "memory", "confirmation"} if source["kind"] == "memory" else {"evidence"}
        if not required <= {ref["type"] for ref in bundle}:
            _v1_fail()
        sources[source["source_id"]] = source
    if not isinstance(context["constraints"], list) or not isinstance(inputs["constraints"], list):
        _v1_fail()
    projected = {}
    for claim in inputs["constraints"]:
        if (not isinstance(claim, dict) or set(claim) != c.ModelConstraint.__required_keys__
                or not _v1_text(claim["id"]) or claim["id"] in projected):
            _v1_fail()
        projected[claim["id"]] = claim
    seen = set()
    for constraint in context["constraints"]:
        if (not isinstance(constraint, dict) or set(constraint) != c.Constraint.__required_keys__
                or not _v1_text(constraint["id"]) or constraint["id"] in seen
                or not isinstance(constraint["target_id"], str) or constraint["target_id"] not in targets
                or type(constraint["confirmed"]) is not bool or constraint["origin"] not in ("explicit", "inferred")):
            _v1_fail()
        seen.add(constraint["id"])
        target = targets[constraint["target_id"]]
        if (not _v1_matches(constraint["selector"], target) or not isinstance(constraint["conditions"], dict)
                or set(constraint["conditions"]) - c.Conditions.__optional_keys__
                or any(not _v1_text(v, 4000) for v in constraint["conditions"].values())):
            _v1_fail()
        registry.validate_binding(constraint["binding"], target["garment_type"])
        spec = constraint["binding"]
        if (not constraint["confirmed"] and (spec["strength"] != "soft" or spec["polarity"] == "indifferent")):
            _v1_fail()
        refs = _v1_refs(constraint["source_refs"])
        binding_ref = constraint["binding_ref"]
        if binding_ref is not None:
            c.validate_ref(binding_ref)
            if binding_ref["type"] != "binding" or binding_ref not in refs:
                _v1_fail()
        if constraint["confirmed"] and (binding_ref is None or not any(r["type"] == "confirmation" for r in refs)):
            _v1_fail()
        claim = projected.get(constraint["id"])
        if claim is None or any(claim[key] != constraint[key] for key in ("target_id", "binding", "selector", "conditions")):
            _v1_fail()
        aliases = claim["source_ids"]
        if (not isinstance(aliases, list) or not aliases or any(not isinstance(a, str) or a not in sources for a in aliases)
                or len(set(aliases)) != len(aliases)
                or any(not _v1_matches(sources[a]["selector"], target) for a in aliases)
                or not refs or refs != _v1_refs([ref for a in aliases for ref in context["source_refs"][a]])):
            _v1_fail()
    if seen != set(projected):
        _v1_fail()
    represented = [constraint["binding_ref"] for constraint in context["constraints"]]
    for constraint in context["constraints"]:
        if constraint["binding"]["polarity"] == "indifferent" and any(
                ref["type"] == "binding" and ref not in represented for ref in constraint["source_refs"]):
            # C2 can bundle a suppressed baseline with the current exception.
            # Its DTO has no spec/strength for that suppressed binding. Do not
            # assume it was soft, or reconstruct it from explanatory prose.
            _v1_fail("context_blocked")


def _v1_empty_targets(inputs: c.ProposalInput, registry: c.RegistryPort) -> list[c.Target]:
    description = registry.describe()
    supported = description["execution"]["supported_garment_types"]
    return [{
        **deepcopy(target),
        "product_information": {
            feature: {"status": "unspecified" if target["garment_type"] in supported and meta["values"] is not None else "unsupported",
                      "values": None, "constraint_ids": [], "source_refs": []}
            for feature, meta in description["product_information"].items()},
        "consumer_needs": {
            category: {subcategory: {
                tag["attribute"]: {"status": "unspecified" if target["garment_type"] in supported else "unsupported",
                                   "preference": None, "constraint_ids": [], "source_refs": []}
                for tag in tags} for subcategory, tags in subcategories.items()}
            for category, subcategories in description["consumer_needs_taxonomy"].items()},
    } for target in inputs["targets"]]


def _v1_conflict(left: c.BindingSpec, right: c.BindingSpec) -> bool:
    if left["polarity"] == right["polarity"] == "indifferent":
        return False
    if "indifferent" in (left["polarity"], right["polarity"]):
        # Explicit indifference only cancels a soft preference axis.
        other = right if left["polarity"] == "indifferent" else left
        return other["strength"] != "hard"
    if left["polarity"] == right["polarity"] == "avoid":
        return False
    if left["domain"] == "FEA":
        return (left["polarity"] == "avoid") != (right["polarity"] == "avoid")
    lv, rv = set(left["values"]), set(right["values"])
    if "avoid" in (left["polarity"], right["polarity"]):
        avoided, positive = (left, right) if left["polarity"] == "avoid" else (right, left)
        av, pv = set(avoided["values"]), set(positive["values"])
        if avoided["match"] == "all":
            return av <= pv if positive["match"] == "all" else pv <= av and len(av) == 1
        return bool(pv & av) if positive["match"] == "all" else pv <= av
    if left["match"] == right["match"] == "all":
        return left["feature"] in ("Type", "Fit", "Price") and lv != rv
    return not bool(lv & rv)


def _v1_model_constraints(proposal: c.Proposal, context: c.MemoryContext) -> list[c.Constraint]:
    inputs = context["model_input"]
    sources = {source["source_id"]: source for source in inputs["sources"]}
    targets = {target["target_id"]: target for target in inputs["targets"]}
    direct = context["constraints"]
    result: list[c.Constraint] = []
    used_ids = {constraint["id"] for constraint in direct}
    for suggestion in proposal["suggestions"]:
        spec, aliases = suggestion["binding"], suggestion["source_ids"]
        if spec["polarity"] == "indifferent" or all(sources[a]["kind"] == "image_selection" for a in aliases):
            _v1_fail("invalid_output")
        # Physical PI values must already occur literally in the evidence or
        # its C2-validated mapping note. Affect/style alone cannot fill color,
        # fiber, price, etc. Korean synonyms are extracted upstream, not guessed
        # again here. FEA remains an explicitly soft interpretation.
        if spec["domain"] == "PI" and any(not any(
                re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", sources[a]["content"], re.IGNORECASE)
                for a in aliases) for value in spec["values"]):
            _v1_fail("invalid_output")
        matching = [constraint for constraint in direct
                    if constraint["target_id"] == suggestion["target_id"] and _v1_path(constraint["binding"]) == _v1_path(spec)]
        if any(_v1_conflict(spec, constraint["binding"]) for constraint in matching):
            _v1_fail("invalid_output")
        # Keep every original any/all clause. A model cannot add inferred
        # values to a field displayed as a confirmed positive specification.
        if any(constraint["confirmed"] and constraint["binding"]["polarity"] in ("prefer", "require", "indifferent")
               for constraint in matching):
            continue
        refs = _v1_refs([ref for alias in aliases for ref in context["source_refs"][alias]])
        if any(item["target_id"] == suggestion["target_id"] and item["binding"] == spec and item["source_refs"] == refs
               for item in direct + result):
            continue
        identifier = f"suggestion-{len(result) + 1}"
        while identifier in used_ids:
            identifier = "model-" + identifier
        used_ids.add(identifier)
        target = targets[suggestion["target_id"]]
        result.append({"id": identifier, "target_id": target["target_id"], "binding_ref": None,
                       "binding": deepcopy(spec), "selector": {"garment_type": target["garment_type"], "slot_id": target["target_id"]},
                       "conditions": {}, "origin": "inferred", "confirmed": False, "source_refs": refs})
    return result


def infer_v1(context: c.MemoryContext, adapter: c.ModelGateway, *, registry: c.RegistryPort) -> c.TargetMap:
    """Build an opt-in, read-only TargetMap; send only ProposalInput to a model.

    C2 resolves current-vs-baseline priority and supplies complete evidence
    bundles (including temporary exceptions). context_id and source_refs link
    the result back to those application/exclusion notes. Inferred clauses are
    scoped to this request/target and its entire dependency basis. No text
    confirmation here can confirm a binding; no TargetMap becomes new evidence.
    """
    context = deepcopy(context)
    _v1_context(context, registry)
    inputs = context["model_input"]
    inputs["registry"] = registry.describe()
    proposal = validate_proposal_v1(adapter.propose(deepcopy(inputs)), inputs, registry)
    constraints = deepcopy(context["constraints"]) + _v1_model_constraints(proposal, context)
    targets = _v1_empty_targets(inputs, registry)
    questions = list(dict.fromkeys(context["questions"] + proposal["questions"]))
    for target in targets:
        paths: dict[tuple[str, ...], list[c.Constraint]] = {}
        for constraint in constraints:
            if constraint["target_id"] == target["target_id"]:
                paths.setdefault(_v1_path(constraint["binding"]), []).append(constraint)
        for path, clauses in paths.items():
            field = (target["product_information"][path[1]] if path[0] == "PI" else
                     target["consumer_needs"][path[1]][path[2]][path[3]])
            field["constraint_ids"] = [clause["id"] for clause in clauses]
            field["source_refs"] = _v1_refs([ref for clause in clauses for ref in clause["source_refs"]])
            if any(_v1_conflict(left["binding"], right["binding"])
                   for i, left in enumerate(clauses) for right in clauses[i + 1:]):
                field["status"] = "conflict"
                questions.append(f"same_priority_conflict: {target['target_id']}의 {'/'.join(path)} 조건을 확인해 주세요. "
                                 f"근거 제약: {', '.join(field['constraint_ids'])}")
                continue
            indifferent = any(clause["binding"]["polarity"] == "indifferent" for clause in clauses)
            effective = [clause for clause in clauses if clause["binding"]["polarity"] != "indifferent"
                         and (not indifferent or clause["binding"]["strength"] == "hard")]
            positive = [clause for clause in effective if clause["binding"]["polarity"] in ("prefer", "require")]
            values_from = positive if path[0] == "PI" else effective
            confirmed = [clause for clause in values_from if clause["confirmed"]]
            values_from = confirmed or values_from
            if values_from:
                field["status"] = "specified" if confirmed else "inferred"
                if path[0] == "PI":
                    field["values"] = list(dict.fromkeys(v for clause in values_from for v in clause["binding"]["values"]))
                else:
                    polarities = {clause["binding"]["polarity"] for clause in values_from}
                    field["preference"] = "require" if "require" in polarities else next(iter(polarities))
            elif indifferent:
                field["status"] = "indifferent"
            # PI avoid-only stays null/unspecified; its executable constraints
            # still carry polarity, strength and each original match operator.
    return {"contract_version": c.CONTRACT_VERSION, "registry_version": registry.version,
            "context_id": context["context_id"], "targets": targets, "constraints": constraints,
            "questions": list(dict.fromkeys(questions)), "basis": deepcopy(context["basis"])}


def validate_target_map_basis(target_map: c.TargetMap, current_context: c.MemoryContext, *,
                              registry: c.RegistryPort, now: datetime) -> None:
    """A2: rebuild C2 from a fresh store snapshot, then call just before use.

    Compare the whole request/profile/object/registry/index/catalog basis and
    context identity; check the clock even when no revision changed. This
    helper does not fetch state and must never receive a UI-provided context.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        _v1_fail()
    try:
        _v1_context(current_context, registry)
        if (not isinstance(target_map, dict) or set(target_map) != c.TargetMap.__required_keys__
                or target_map["contract_version"] != c.CONTRACT_VERSION or target_map["registry_version"] != registry.version
                or target_map["context_id"] != current_context["context_id"]
                or _v1_basis(target_map["basis"], registry) != _v1_basis(current_context["basis"], registry)
                or target_map["basis"]["valid_until"] is not None and _v1_time(target_map["basis"]["valid_until"]) <= now):
            _v1_fail("stale_context")
    except StyleMateError:
        _v1_fail("stale_context")


__all__ = ["ModelAdapter", "RuleAdapter", "infer", "infer_v1", "validate_target_map_basis"]
