"""Target feature inference and a network-free adapter contract.

The adapter boundary is intentionally small.  An external Responses adapter
can implement ``propose`` later, while this module keeps vocabulary checks,
target applicability, and user constraints in application code.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol

from .errors import StyleMateError
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


__all__ = ["ModelAdapter", "RuleAdapter", "infer"]
