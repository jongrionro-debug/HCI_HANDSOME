"""Opt-in v1 memory retrieval over the store's authoritative SQLite snapshot.

No SQL, network, embeddings or writes live here. SemanticSearch must either
serve the exact supplied index_version completely, or raise (stale_context for
an old/incomplete index). Its hits are intersected with eligible ObjectRefs.
The fixed protocol has no index metadata response; a dishonest adapter cannot
be audited for omitted hits here. Structural/keyword retrieval also works alone.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
import unicodedata
from typing import Any

from . import contracts as c
from .errors import StyleMateError


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def _ref(kind: str, obj: dict) -> c.ObjectRef:
    return {"type": kind, "id": obj["id"], "version": obj["version"]}


def _refs(items: list[c.ObjectRef]) -> list[c.ObjectRef]:
    return [dict(zip(("type", "id", "version"), key)) for key in sorted({
        (r["type"], r["id"], r["version"]) for r in items
    })]


def _meaning(memory: dict) -> dict:
    return {key: deepcopy(memory[key]) for key in c.MemoryMeaning.__required_keys__}


def _spec(binding: dict) -> dict:
    keys = c.PIBindingSpec.__required_keys__ if binding.get("domain") == "PI" else c.FEABindingSpec.__required_keys__
    return {key: deepcopy(binding[key]) for key in keys}


def _selector(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"garment_type", "slot_id"}
            and all(v is None or isinstance(v, str) and 0 < len(v.strip()) <= 128 for v in value.values()))


def _matches(selector: dict, target: dict) -> bool:
    return (selector["garment_type"] in (None, target["garment_type"])
            and selector["slot_id"] in (None, target["target_id"]))


def _conditions(value: Any) -> bool:
    return (isinstance(value, dict) and not set(value) - {"occasion", "activity", "goal"}
            and all(isinstance(v, str) and 0 < len(v.strip()) <= 4000 for v in value.values()))


def _condition_match(conditions: dict, facts: dict) -> bool:
    return all(facts.get(key) == value for key, value in conditions.items())


class _Snapshot:
    """Resolve versioned, owned, retained dependencies before relevance scoring."""

    def __init__(self, snapshot: c.MemorySnapshot, registry: c.RegistryPort, targets: list[c.TargetSpec]):
        self.snapshot = snapshot
        self.problems: set[str] = set()
        if not isinstance(snapshot, dict) or snapshot.get("contract_version") != c.CONTRACT_VERSION:
            raise StyleMateError("unsupported_contract", "v1 snapshot이 필요합니다.")
        if not c.MemorySnapshot.__required_keys__ <= snapshot.keys():
            self.problems.add("snapshot_incomplete")
        self.request = snapshot.get("request", {})
        if not isinstance(self.request, dict):
            raise StyleMateError("invalid_input", "snapshot의 request가 유효하지 않습니다.")
        if (registry.version != c.V1_REGISTRY_VERSION or snapshot.get("registry_version") != registry.version
                or self.request.get("contract_version") != c.CONTRACT_VERSION
                or self.request.get("registry_version") != registry.version):
            raise StyleMateError("unsupported_contract", "snapshot과 사전 계약이 다릅니다.")
        try:
            self.now = _time(snapshot["now"])
            if min(_time(self.request[k]) for k in ("retention_until", "max_until")) <= self.now:
                raise StyleMateError("request_expired", "요청이 만료되었습니다.")
            if self.request["status"] != "open":
                raise StyleMateError("request_closed", "열린 요청에서만 목표 근거를 조회합니다.")
            if (not isinstance(self.request["id"], str) or not self.request["id"]
                    or not isinstance(self.request["user_id"], str) or not self.request["user_id"]
                    or type(self.request["revision"]) is not int or self.request["revision"] < 1
                    or type(snapshot["profile_revision"]) is not int or snapshot["profile_revision"] < 0):
                raise ValueError("invalid revisions")
        except (KeyError, TypeError, ValueError):
            raise StyleMateError("invalid_input", "snapshot의 요청·시각·revision이 유효하지 않습니다.") from None
        if (not isinstance(targets, list) or not targets
                or any(not isinstance(t, dict) or set(t) != {"target_id", "garment_type"}
                       or any(not isinstance(v, str) or not 0 < len(v.strip()) <= 128 for v in t.values())
                       or t not in self.request.get("targets", []) for t in targets)
                or len({t["target_id"] for t in targets}) != len(targets)):
            raise StyleMateError("invalid_input", "현재 요청에 속하는 중복 없는 targets가 필요합니다.")
        self.targets = sorted(deepcopy(targets), key=lambda t: t["target_id"])
        self.objects: dict[tuple[str, str], dict] = {}
        self.deadlines = [_time(self.request[k]) for k in ("retention_until", "max_until")]
        for kind, key in (("memory", "memories"), ("evidence", "evidence"), ("binding", "bindings"),
                          ("confirmation", "confirmations"), ("consent", "consents"),
                          ("question", "questions"), ("interpretation", "interpretations")):
            items = snapshot.get(key)
            if not isinstance(items, list):
                self.problems.add("snapshot_incomplete")
                continue
            duplicates = set()
            for obj in items:
                if not self.owned(obj):
                    continue
                identity = (kind, obj["id"])
                if identity in self.objects:
                    duplicates.add(identity)
                    self.problems.add("snapshot_ambiguous_version")
                self.objects[identity] = obj
            for identity in duplicates:
                self.objects.pop(identity, None)

    def owned(self, obj: Any) -> bool:
        if (not isinstance(obj, dict) or obj.get("user_id") != self.request["user_id"]
                or obj.get("request_id") not in (None, self.request["id"])
                or obj.get("contract_version") != c.CONTRACT_VERSION
                or not isinstance(obj.get("id"), str) or not 0 < len(obj["id"]) <= 128
                or type(obj.get("version")) is not int or obj["version"] < 1):
            return False
        try:
            return _time(obj["created_at"]) <= self.now < _time(obj["retention_until"])
        except (KeyError, TypeError, ValueError):
            return False

    def resolve(self, ref: Any, kinds: tuple[str, ...]) -> dict:
        c.validate_ref(ref)
        obj = self.objects.get((ref["type"], ref["id"]))
        if ref["type"] not in kinds or obj is None or obj["version"] != ref["version"]:
            raise ValueError("missing, invalid or stale dependency")
        return obj

    def memory_shape(self, memory: dict) -> bool:
        try:
            if (set(memory) != c.MemoryItem.__required_keys__ or "legacy" in memory
                    or memory["scope"] not in ("short_term", "long_term")
                    or memory["request_id"] != (self.request["id"] if memory["scope"] == "short_term" else None)
                    or not _selector(memory["selector"]) or not _conditions(memory["conditions"])
                    or memory["scope"] == "long_term" and memory["selector"]["slot_id"] is not None
                    or memory["origin"] not in ("explicit", "inferred") or type(memory["confirmed"]) is not bool
                    or memory["status"] not in ("candidate", "active")
                    or memory["kind"] not in ("preference", "requirement", "situation")
                    or memory["polarity"] not in ("prefer", "avoid", "require", "indifferent")
                    or memory["strength"] not in ("soft", "hard")
                    or memory["polarity"] == "indifferent" and memory["strength"] != "soft"
                    or not isinstance(memory["content"], str) or not 0 < len(memory["content"].strip()) <= 4000
                    or not isinstance(memory["family_id"], str) or not memory["family_id"]):
                return False
            fact = memory["fact"]
            if fact is not None and (memory["kind"] != "situation" or not isinstance(fact, dict)
                                     or set(fact) != {"key", "value"} or not _conditions({fact["key"]: fact["value"]})):
                return False
            start, end = memory["valid_from"], memory["valid_until"]
            if start is not None:
                if _time(start) > self.now:
                    self.deadlines.append(_time(start))
                    return False
            if end is not None and _time(end) <= self.now:
                return False
            return start is None or end is None or _time(start) < _time(end)
        except (KeyError, TypeError, ValueError):
            return False

    def sources(self, refs: Any, *, request_id: str | None, seen: frozenset = frozenset()) -> list[c.ObjectRef]:
        if not isinstance(refs, list) or not 1 <= len(refs) <= 64 or len(seen) > 64:
            raise ValueError("invalid evidence bundle")
        result = []
        for ref in refs:
            obj = self.resolve(ref, ("evidence", "memory"))
            identity = (ref["type"], ref["id"])
            if identity in seen or request_id is None and obj["request_id"] is not None:
                raise ValueError("cyclic or non-independent evidence")
            if ref["type"] == "memory":
                if not self.memory_shape(obj):
                    raise ValueError("invalid source memory")
                result.extend(self.sources(obj["source_refs"], request_id=request_id, seen=seen | {identity}))
                if obj["status"] == "active" and obj["confirmed"]:
                    result.extend(self.proof(obj, "confirmation", seen=seen | {identity}))
                    if obj["scope"] == "long_term":
                        result.extend(self.proof(obj, "consent", seen=seen | {identity}))
                elif obj["scope"] == "long_term":
                    raise ValueError("unconfirmed long-term dependency")
            elif (set(obj) != c.Evidence.__required_keys__ or not _selector(obj.get("selector")) or obj.get("kind") not in (
                    "user_text", "image_selection", "ui_response", "consent_snapshot")):
                raise ValueError("invalid evidence")
            elif obj["kind"] == "user_text" and (not isinstance(obj.get("quote"), str) or not 0 < len(obj["quote"].strip()) <= 4000):
                raise ValueError("missing quote")
            elif obj["kind"] == "image_selection" and not isinstance(obj.get("selection"), dict):
                raise ValueError("missing selection fact")
            elif obj["kind"] == "consent_snapshot" and not isinstance(obj.get("snapshot"), dict):
                raise ValueError("missing independent snapshot")
            elif obj["kind"] == "ui_response" and not any(
                    isinstance(obj.get(key), str) and obj[key].strip() for key in ("quote", "context")):
                c.validate_ref(obj.get("display_ref"))
                if obj["display_ref"]["type"] != "display":
                    raise ValueError("empty UI evidence")
            result.append(ref)
        return _refs(result)

    def proof(self, memory: dict, kind: str, binding: dict | None = None, *, seen: frozenset = frozenset()) -> list[c.ObjectRef]:
        ref = (binding or memory)["confirmation_ref" if kind == "confirmation" else "consent_ref"]
        proof = self.resolve(ref, (kind,))
        snapshot = proof.get("snapshot")
        if (proof["request_id"] != memory["request_id"] or proof.get("memory_id") != memory["id"]
                or not isinstance(snapshot, dict) or snapshot.get("meaning") != _meaning(memory)
                or not isinstance(snapshot.get("bindings"), list) or not isinstance(snapshot.get("subject_refs"), list)):
            raise ValueError("confirmation/consent meaning mismatch")
        c.validate_ref(proof.get("event_ref"))
        if proof["event_ref"]["type"] != "event":
            raise ValueError("missing trusted event")
        if kind == "consent" and (proof.get("status") != "active" or proof.get("purpose") != "future_reuse"):
            raise ValueError("no active future reuse consent")
        if binding is not None:
            current = _ref("binding", binding)
            # Confirmation is a state transition: B increments the binding
            # version after checking the exact displayed pre-transition ref.
            # New independent snapshots can already name the current version.
            displayed = current | {"version": current["version"] - 1}
            if (_spec(binding) not in snapshot["bindings"]
                    or current not in snapshot["subject_refs"]
                    and not (displayed["version"] >= 1 and displayed in snapshot["subject_refs"])):
                raise ValueError("binding itself was not confirmed")
        sources = self.sources(proof.get("source_refs"), request_id=memory["request_id"], seen=seen)
        if memory["scope"] == "long_term" and not any(
            self.resolve(r, ("evidence",)).get("snapshot") == _meaning(memory)
            for r in sources if r["type"] == "evidence"
        ):
            raise ValueError("no independent long-term meaning snapshot")
        return [ref, *sources]

    def bundle(self, memory: dict) -> list[c.ObjectRef]:
        refs = [_ref("memory", memory), *self.sources(memory["source_refs"], request_id=memory["request_id"])]
        if memory["status"] == "active" and memory["confirmed"] is True:
            refs.extend(self.proof(memory, "confirmation"))
            if memory["scope"] == "long_term":
                refs.extend(self.proof(memory, "consent"))
        elif memory["scope"] != "short_term" or memory["status"] != "candidate" or memory["confirmed"]:
            raise ValueError("not a confirmed memory or current hypothesis")
        return _refs(refs)

    def applies(self, refs: list[c.ObjectRef], target: dict, facts: dict, *, check_conditions: bool = True) -> bool:
        for ref in refs:
            obj = self.resolve(ref, (ref["type"],))
            if "selector" in obj and not _matches(obj["selector"], target):
                return False
            if obj.get("kind") == "image_selection" and obj["selection"].get("target_id") != target["target_id"]:
                return False
            if check_conditions and ref["type"] == "memory" and not _condition_match(obj["conditions"], facts):
                return False
        return True


@dataclass
class _Entry:
    memory: dict
    target: dict
    refs: list[c.ObjectRef]
    bindings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    suppressed: set[str] = field(default_factory=set)
    mandatory: bool = False
    origins: set[str] = field(init=False)

    def __post_init__(self):
        # Added condition proofs are dependencies, not independent preference
        # origins. Do not merge unrelated memories merely sharing an occasion.
        self.origins = {ref["id"] for ref in self.refs if ref["type"] == "evidence"}

    @property
    def priority(self) -> tuple[int, int]:
        return (int(self.memory["scope"] == "short_term"), int(self.memory["origin"] == "explicit"))


def _facts(entries: list[_Entry], reader: _Snapshot) -> tuple[dict, list[_Entry], list[tuple[_Entry, _Entry]], set[str]]:
    """Recompute conditional facts to a fixed point; never retain an old premise."""
    facts: dict = {}
    seen = set()
    while True:
        groups: dict[str, list[_Entry]] = {}
        for entry in entries:
            m = entry.memory
            if m["fact"] is not None and m["confirmed"] and m["status"] == "active" and m["polarity"] in ("prefer", "require"):
                if reader.applies(entry.refs, entry.target, facts):
                    groups.setdefault(m["fact"]["key"], []).append(entry)
        result, selected, overrides, conflicts = {}, [], [], set()
        for key, candidates in sorted(groups.items()):
            priority = max(e.priority for e in candidates)
            top = [e for e in candidates if e.priority == priority]
            if len({e.memory["fact"]["value"] for e in top}) > 1:
                conflicts.add(key)
                continue
            result[key] = top[0].memory["fact"]["value"]
            selected.extend(top)
            overrides.extend((loser, top[0]) for loser in candidates if loser.priority < priority
                             and loser.memory["fact"]["value"] != result[key])
        if result == facts:
            return result, selected, overrides, conflicts
        state = _json(result)
        if state in seen:
            return {}, [], [], {"conditional_fact_cycle"}
        seen.add(state)
        facts = result


def _path(spec: dict) -> str:
    return "/".join(["PI", spec["feature"]] if spec["domain"] == "PI" else
                    ["FEA", spec["category"], spec["subcategory"], spec["tag"]])


def _conflict(left: dict, right: dict) -> bool:
    if left["polarity"] == right["polarity"] == "indifferent":
        return False
    if "indifferent" in (left["polarity"], right["polarity"]):
        return True
    if left["polarity"] == right["polarity"] == "avoid":
        return False
    if left["domain"] == "FEA":
        return (left["polarity"] == "avoid") != (right["polarity"] == "avoid")
    lv, rv = set(left["values"]), set(right["values"])
    if "avoid" in (left["polarity"], right["polarity"]):
        positive, avoided = (right, lv) if left["polarity"] == "avoid" else (left, rv)
        return bool(set(positive["values"]) & avoided) if positive["match"] == "all" else set(positive["values"]) <= avoided
    if left["match"] == right["match"] == "any":
        return not bool(lv & rv)
    if left["match"] != right["match"]:
        return not bool(lv & rv)
    return left["feature"] in ("Type", "Fit", "Price") and lv != rv


def _bindings(reader: _Snapshot, entry: _Entry, registry: c.RegistryPort, facts: dict, *, hypothesis: bool = False) -> None:
    memory = entry.memory
    for (kind, _), binding in sorted(reader.objects.items()):
        if kind != "binding" or binding.get("memory_id") != memory["id"]:
            continue
        if binding.get("status") not in ("candidate", "active"):
            continue
        try:
            fields = c.PIBinding.__required_keys__ if binding.get("domain") == "PI" else c.FEABinding.__required_keys__
            if (set(binding) != fields or binding.get("subject") != "user_target" or binding.get("registry_version") != registry.version
                    or binding["request_id"] != memory["request_id"] or type(binding.get("confirmed")) is not bool
                    or binding.get("origin") not in ("explicit", "inferred")):
                raise ValueError("invalid binding state")
            spec = _spec(binding)
            registry.validate_binding(spec, entry.target["garment_type"])
            if spec["polarity"] != memory["polarity"]:
                raise ValueError("binding polarity does not match memory")
            refs = [_ref("binding", binding), *reader.sources(binding["source_refs"], request_id=memory["request_id"])]
            executable = binding["confirmed"] and binding["status"] == "active"
            if hypothesis and binding["confirmed"]:
                raise ValueError("binding cannot confirm an unconfirmed memory")
            if executable:
                refs.extend(reader.proof(memory, "confirmation", binding))
            elif spec["strength"] != "soft" or spec["polarity"] == "indifferent":
                raise ValueError("unconfirmed hard/indifferent binding")
            if not reader.applies(refs, entry.target, facts):
                raise ValueError("binding source scope does not match")
            entry.refs = _refs(entry.refs + refs)
            if executable:
                entry.bindings.append(binding)
                entry.mandatory = True  # direct soft constraints are retained too
            else:
                entry.notes.append("미확인 soft 매핑(지정 아님): " + _json(spec))
        except (KeyError, TypeError, ValueError, StyleMateError):
            # Keep the original natural memory. Never invent a replacement map.
            reader.problems.add("binding_unavailable")
            entry.notes.append("매핑 검증 불가: 원래 문장을 보존하고 값을 확정하지 않음")
    if not hypothesis and memory["strength"] == "hard" and not any(b["strength"] == "hard" for b in entry.bindings):
        entry.notes.append("unmapped_hard_requirement: 필수 문장의 매핑 확인이 필요함")
        reader.problems.add("unmapped_hard_requirement")


def _resolve_bindings(entries: list[_Entry]) -> tuple[list[tuple[_Entry, _Entry]], list[str]]:
    groups: dict[str, list[tuple[_Entry, dict]]] = {}
    for entry in entries:
        for binding in entry.bindings:
            groups.setdefault(_path(binding), []).append((entry, binding))
    unions, questions = [], []
    for path, claims in sorted(groups.items()):
        # Resolve from the highest priority down so a suppressed claim cannot
        # suppress a third, otherwise compatible current constraint.
        survivors: list[tuple[_Entry, dict]] = []
        for entry, binding in sorted(claims, key=lambda pair: (tuple(-v for v in pair[0].priority), pair[0].memory["id"])):
            higher = [(other, b) for other, b in survivors if other.priority > entry.priority and _conflict(binding, b)]
            if higher:
                entry.suppressed.add(path)
                winner = higher[0][0]
                entry.notes.append(f"이번 요청 예외: {path}는 현재 요구로 일시 대체; 장기 원본은 유지")
                unions.append((entry, winner))
            else:
                survivors.append((entry, binding))
        disputed = set()
        for index, (left, lb) in enumerate(survivors):
            for right, rb in survivors[index + 1:]:
                if left.priority == right.priority and _conflict(lb, rb):
                    disputed.update((id(left), id(right)))
                    unions.append((left, right))
        if disputed:
            questions.append(f"same_priority_conflict: {entries[0].target['target_id']}의 {path} 조건 중 무엇을 적용할까요?")
            # Withhold the disputed path as a whole, including compatible
            # duplicates; no source ordering or score is a tie breaker.
            for entry, _binding in survivors:
                entry.suppressed.add(path)
                entry.mandatory = True
                entry.notes.append(f"동일 우선순위 상충: {path} 해석 보류, 사용자 질문 필요")
    return unions, questions


# Retrieval aliases only: these terms never create a PI/FEA binding or a fact.
_ALIASES = (
    ("vintage", ("빈티지", "레트로", "복고", "retro")),
    ("casual", ("캐주얼", "캐쥬얼")),
    ("formal", ("포멀", "정장", "격식")),
    ("comfortable", ("편안", "편한", "쾌적", "comfy")),
    ("wide", ("와이드", "넉넉", "여유로", "여유로운")),
    ("slim", ("슬림", "좁은", "슬림한")),
    ("pants", ("바지", "팬츠")),
    ("shirt", ("셔츠",)),
    ("presentation", ("발표", "프레젠테이션")),
)


def _terms(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    for canonical, aliases in _ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            text = text.replace(alias, " " + canonical + " ")
    tokens = set(re.findall(r"[a-z0-9]+|[가-힣]+", text))
    # Small Hangul ngrams preserve arbitrary expressions despite particles.
    tokens.update(word[i:i + 2] for word in tuple(tokens) if re.fullmatch(r"[가-힣]{3,}", word)
                  for i in range(len(word) - 1))
    return {token for token in tokens if len(token) > 1}


def _group_entries(entries: list[_Entry], unions: list[tuple[_Entry, _Entry]]) -> list[list[_Entry]]:
    parents = {id(e): id(e) for e in entries}

    def root(identity):
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    seen = {}
    for entry in entries:
        target_id = entry.target["target_id"]
        keys = [(target_id, "family", entry.memory["family_id"])] + [
            (target_id, "evidence", identifier) for identifier in sorted(entry.origins)]
        for key in keys:
            if key in seen:
                parents[root(id(entry))] = root(seen[key])
            seen[key] = id(entry)
    for left, right in unions:
        parents[root(id(left))] = root(id(right))
    groups: dict[int, list[_Entry]] = {}
    for entry in entries:
        groups.setdefault(root(id(entry)), []).append(entry)
    return [sorted(group, key=lambda e: (tuple(-v for v in e.priority), e.memory["id"])) for group in groups.values()]


def _description(entry: _Entry) -> str:
    m = entry.memory
    if m["fact"] is not None:
        role = "확인된 사실 " + _json(m["fact"])
    elif entry.bindings or m["strength"] == "hard" or m["kind"] == "requirement" or m["polarity"] == "require":
        role = "직접 제약"
    else:
        role = "자유 표현 기억"
    return (f"{role}: {m['content']}\n"
            f"범위={m['scope']}; 원출처={m['origin']}; 내용확인=true; 방향={m['polarity']}; 강도={m['strength']}; "
            f"대상={_json(m['selector'])}; 조건={_json(m['conditions'])}; "
            f"기간={_json([m['valid_from'], m['valid_until']])}"
            + ("\n" + "\n".join(sorted(set(entry.notes))) if entry.notes else ""))


def _rank(groups: list[list[_Entry]], queries: dict[str, str], hits: list[c.ObjectRef]) -> list[list[_Entry]]:
    def stable(group):
        return (group[0].target["target_id"], tuple(sorted(e.memory["id"] for e in group)))

    def structural(group):
        return max((int(e.memory["selector"]["slot_id"] is not None),
                    int(e.memory["selector"]["garment_type"] is not None), len(e.memory["conditions"])) for e in group)

    def lexical(group):
        return len(_terms(queries[group[0].target["target_id"]]) & _terms(" ".join(e.memory["content"] for e in group)))

    channels = [sorted(groups, key=lambda g: (tuple(-v for v in structural(g)), stable(g))),
                sorted([g for g in groups if lexical(g)], key=lambda g: (-lexical(g), stable(g)))]
    semantic_order = {(r["id"], r["version"]): index for index, r in enumerate(hits)}

    def semantic_rank(group):
        return min((semantic_order.get((e.memory["id"], e.memory["version"]), len(hits)) for e in group), default=len(hits))

    channels.append(sorted([g for g in groups if semantic_rank(g) < len(hits)], key=lambda g: (semantic_rank(g), stable(g))))
    scores = {id(g): 0.0 for g in groups}
    for channel in channels:
        for position, group in enumerate(channel, 1):
            scores[id(group)] += 1 / (60 + position)
    return sorted(groups, key=lambda g: (not any(e.mandatory for e in g), -scores[id(g)], stable(g)))


def _assemble(reader: _Snapshot, groups: list[list[_Entry]], hypotheses: list[_Entry], questions: list[dict],
              query_refs: list[c.ObjectRef], registry: c.RegistryPort, index_version: str | None,
              clarification: list[str]) -> c.MemoryContext:
    sources, constraints, model_constraints, bundles = [], [], [], {}
    emitted_questions = list(clarification)
    for number, group in enumerate(groups, 1):
        alias = f"s{number:03}"
        refs = _refs([ref for entry in group for ref in entry.refs])
        bundles[alias] = refs
        target = group[0].target
        sources.append({"source_id": alias, "kind": "memory",
                        "content": "\n\n".join(dict.fromkeys(_description(e) for e in group)),
                        "selector": {"garment_type": target["garment_type"], "slot_id": target["target_id"]}})
        unique = set()
        for entry in group:
            for binding in entry.bindings:
                spec = _spec(binding)
                key = _json([spec, entry.memory["selector"], entry.memory["conditions"]])
                if _path(spec) in entry.suppressed or key in unique:
                    continue
                unique.add(key)
                constraint = {"id": f"c{len(constraints) + 1:03}", "target_id": target["target_id"],
                              "binding_ref": _ref("binding", binding), "binding": spec,
                              "selector": deepcopy(entry.memory["selector"]),
                              "conditions": deepcopy(entry.memory["conditions"]),
                              "origin": binding["origin"], "confirmed": True, "source_refs": deepcopy(refs)}
                constraints.append(constraint)
                model_constraints.append({key: deepcopy(constraint[key]) for key in
                                          ("id", "target_id", "binding", "selector", "conditions")} | {"source_ids": [alias]})
    # Hypotheses have a separate alias/bundle and appear only as questions.
    # They never enter ProposalInput.sources, facts, or executable constraints.
    for group in _group_entries(hypotheses, []):
        alias = f"q{len(bundles) + 1:03}"
        bundles[alias] = _refs([ref for entry in group for ref in entry.refs])
        text = " / ".join(dict.fromkeys(
            f"{e.memory['content']} (대상={_json(e.memory['selector'])}, 조건={_json(e.memory['conditions'])})"
            for e in group))
        emitted_questions.append(f"unconfirmed_hypothesis [{alias}] {group[0].target['target_id']}: {text} — 이 해석이 맞나요?")
    for question in questions:
        alias = f"q{len(bundles) + 1:03}"
        bundles[alias] = _refs([_ref("question", question), *question["subject_refs"]])
        emitted_questions.append(f"[{alias}] {question['text']}")
    versions = _refs(query_refs + [ref for refs in bundles.values() for ref in refs])
    deadlines = list(reader.deadlines)
    for ref in versions:
        obj = reader.resolve(ref, (ref["type"],))
        deadlines.append(_time(obj["retention_until"]))
        if obj.get("valid_until") is not None:
            deadlines.append(_time(obj["valid_until"]))
    return {
        "context_id": "", "basis": {
            "request_id": reader.request["id"], "request_revision": reader.request["revision"],
            "profile_revision": reader.snapshot["profile_revision"], "object_versions": versions,
            "contract_version": c.CONTRACT_VERSION, "registry_version": registry.version,
            "index_version": index_version, "catalog": None, "valid_until": min(deadlines).isoformat(),
        },
        "model_input": {"sources": sources, "targets": deepcopy(reader.targets),
                        "registry": registry.describe(), "constraints": model_constraints},
        "source_refs": bundles, "constraints": constraints, "questions": sorted(set(emitted_questions)),
        "blocked": False, "retrieval_status": "complete",
    }


def _fits(context: c.MemoryContext, char_budget: int) -> bool:
    # Count complete evidence bundles, including targets/conditions/exceptions.
    # Registry vocabulary and freshness metadata have separate wire limits.
    material = {key: context[key] for key in ("source_refs", "constraints", "questions")}
    material["model_input"] = {key: context["model_input"][key] for key in ("sources", "targets", "constraints")}
    return (len(_json(material)) <= char_budget and len(context["basis"]["object_versions"]) <= 256
            and len(context["model_input"]["sources"]) <= 64
            and len(_json(context["model_input"]).encode("utf-8")) <= 256 * 1024
            and all(len(source["content"]) <= 4000 for source in context["model_input"]["sources"]))


def build_context_v1(snapshot: c.MemorySnapshot, targets: list[c.TargetSpec], *, registry: c.RegistryPort,
                     semantic: c.SemanticSearch | None = None, char_budget: int = 6000) -> c.MemoryContext:
    """Filter -> reserve direct/hard conditions -> rank -> bundle, with no writes.

    The budget counts serialized memory material (not registry/basis). Mandatory
    material is retained intact on overflow and blocked=True prevents model use.
    Optional groups are removed atomically and reported as partial retrieval.
    Only model_input may be sent to a model. questions hold hypotheses/errors;
    source_refs and basis remain internal. The legacy builder is unchanged.
    """
    if type(char_budget) is not int or char_budget < 256:
        raise StyleMateError("invalid_input", "char_budget는 256 이상의 정수여야 합니다.")
    reader = _Snapshot(snapshot, registry, targets)
    records = []
    for (kind, _), memory in sorted(reader.objects.items()):
        if (kind != "memory" or not reader.memory_shape(memory)
                or not any(_matches(memory["selector"], target) for target in reader.targets)):
            continue
        try:
            refs = reader.bundle(memory)
            records.append((memory, refs))
            for ref in refs:
                obj = reader.resolve(ref, (ref["type"],))
                reader.deadlines.append(_time(obj["retention_until"]))
                if obj.get("valid_until") is not None:
                    reader.deadlines.append(_time(obj["valid_until"]))
        except (KeyError, TypeError, ValueError, StyleMateError):
            reader.problems.add("evidence_bundle_unavailable")
    groups, hypotheses, clarification, queries, query_refs = [], [], [], {}, []
    for target in reader.targets:
        entries = [_Entry(m, target, list(refs)) for m, refs in records
                   if reader.applies(refs, target, {}, check_conditions=False)]
        facts, fact_entries, fact_overrides, fact_conflicts = _facts(entries, reader)
        if fact_conflicts:
            clarification.extend(f"same_priority_fact_conflict: {target['target_id']}의 {key}를 확인해 주세요."
                                 for key in sorted(fact_conflicts))
            # Preserve both conflicting facts for question provenance, but
            # prevent either value from satisfying a memory condition.
            fact_entries.extend(e for e in entries if e.memory["confirmed"] and e.memory["fact"] is not None
                                and (e.memory["fact"]["key"] in fact_conflicts or "conditional_fact_cycle" in fact_conflicts)
                                and e not in fact_entries)
        fact_refs = _refs([ref for e in fact_entries for ref in e.refs])
        usable = []
        for entry in entries:
            m = entry.memory
            if not reader.applies(entry.refs, target, facts):
                continue
            if not m["confirmed"]:
                _bindings(reader, entry, registry, facts, hypothesis=True)
                if m["strength"] == "hard":
                    reader.problems.add("unconfirmed_hard_requirement")
                if m["conditions"]:
                    entry.refs = _refs(entry.refs + fact_refs)
                hypotheses.append(entry)
                continue
            if m["fact"] is not None and entry not in fact_entries:
                continue
            entry.mandatory = m["scope"] == "short_term" or m["strength"] == "hard" or m["fact"] is not None
            if m["conditions"]:
                entry.refs = _refs(entry.refs + fact_refs)
            if m["fact"] is None:
                _bindings(reader, entry, registry, facts)
            usable.append(entry)
        fact_unions = []
        for loser, winner in fact_overrides:
            if winner not in usable:
                continue
            loser.notes.append("이번 요청 예외: 장기 상황은 이번 목표에서만 제외하고 원본을 유지")
            loser.mandatory = True
            usable.append(loser)
            fact_unions.append((loser, winner))
        unions, questions = _resolve_bindings(usable)
        clarification.extend(questions)
        groups.extend(_group_entries(usable, unions + fact_unions))
        query_parts = [target["garment_type"], *facts.values()]
        for (kind, _), evidence in sorted(reader.objects.items()):
            if (kind == "evidence" and evidence["request_id"] == reader.request["id"]
                    and evidence.get("kind") == "user_text" and _selector(evidence.get("selector"))
                    and _matches(evidence["selector"], target) and isinstance(evidence.get("quote"), str)):
                query_parts.append(evidence["quote"])
                query_refs.append(_ref("evidence", evidence))
        queries[target["target_id"]] = "\n".join(query_parts)
    eligible_refs = _refs([_ref("memory", e.memory) for group in groups for e in group])
    index_version, hits = None, []
    if semantic is not None and eligible_refs:
        index_version = "memory-" + _digest({"eligible": eligible_refs, "registry": registry.version,
                                           "request_revision": reader.request["revision"],
                                           "profile_revision": snapshot["profile_revision"],
                                           "dependencies": _refs([ref for group in groups for e in group for ref in e.refs])})
        try:
            raw = semantic.search("\n".join(queries.values()), deepcopy(eligible_refs), index_version=index_version)
            if not isinstance(raw, list):
                raise ValueError("semantic response must be references")
            for ref in raw:
                c.validate_ref(ref)
                if ref not in eligible_refs:
                    code = "semantic_stale_index" if any(r["type"] == ref["type"] and r["id"] == ref["id"] for r in eligible_refs) else "semantic_ineligible_ref"
                    reader.problems.add(code)
                elif ref not in hits:
                    hits.append(ref)
        except StyleMateError as exc:
            reader.problems.add("semantic_stale_index" if exc.code == "stale_context" else "semantic_unavailable")
        except Exception:
            # Adapter exceptions are opaque; never expose provider bodies/IDs.
            reader.problems.add("semantic_unavailable")
    question_subjects: dict[str, set[tuple]] = {}
    for entry in [e for group in groups for e in group] + hypotheses:
        question_subjects.setdefault(entry.target["target_id"], set()).update(
            (r["type"], r["id"], r["version"]) for r in entry.refs)
    stored_questions = []
    for (kind, _), obj in sorted(reader.objects.items()):
        if kind == "interpretation" and obj["request_id"] == reader.request["id"]:
            query_refs.append(_ref(kind, obj))
            if obj.get("status") != "complete":
                reader.problems.add("interpretation_pending")
        if (kind == "question" and obj["request_id"] == reader.request["id"] and obj.get("status") == "open"
                and obj.get("target_id") in (None, *(t["target_id"] for t in reader.targets))):
            try:
                if not isinstance(obj.get("text"), str) or not obj["text"].strip() or not isinstance(obj.get("subject_refs"), list):
                    raise ValueError("invalid question")
                eligible_ids = set().union(*(question_subjects.values())) if obj["target_id"] is None else question_subjects.get(obj["target_id"], set())
                for ref in obj["subject_refs"]:
                    c.validate_ref(ref)
                    if (ref["type"], ref["id"], ref["version"]) not in eligible_ids:
                        raise ValueError("ineligible question subject")
                stored_questions.append(obj)
            except (ValueError, StyleMateError):
                reader.problems.add("question_unavailable")
    ranked = _rank(groups, queries, hits)
    selected = [g for g in ranked if any(e.mandatory for e in g)]

    def assemble(chosen):
        return _assemble(reader, chosen, hypotheses, stored_questions, _refs(query_refs), registry,
                         index_version, clarification + sorted(reader.problems))

    context = assemble(selected)
    overflow = not _fits(context, char_budget)
    omitted = False
    if not overflow:
        for group in ranked:
            if any(e.mandatory for e in group):
                continue
            proposal = assemble(selected + [group])
            if _fits(proposal, char_budget):
                selected.append(group)
                context = proposal
            else:
                omitted = True
    if omitted and not overflow:
        note = "context_budget_partial: 예산 때문에 선택적 기억 묶음 일부를 제외했습니다."
        context["questions"].append(note)
        while not _fits(context, char_budget):
            optional = [g for g in selected if not any(e.mandatory for e in g)]
            if not optional:
                overflow = True
                break
            selected.remove(optional[-1])
            context = assemble(selected)
            context["questions"].append(note)
    if overflow:
        context["questions"].append("context_budget_insufficient: 근거 묶음 예산이 부족합니다.")
    available = bool(context["model_input"]["sources"])
    if not available:
        context["questions"].append("insufficient_evidence: 적용할 확인된 기억이 부족합니다.")
    context["retrieval_status"] = "unavailable" if not available else "partial" if reader.problems or overflow or omitted else "complete"
    context["blocked"] = bool(reader.problems or overflow or clarification or not available)
    context["questions"] = sorted(set(context["questions"]))
    context["context_id"] = "ctx_v1_" + _digest({key: value for key, value in context.items() if key != "context_id"})[:24]
    return context
