"""FEA-grounded PI proposals stay separate from executable direct constraints."""

from copy import deepcopy
import hashlib
import json

from .catalog_validation import canonical
from . import contracts as c
from .errors import StyleMateError
from .inference import infer_v1
from .model_io import validate_proposal_v1


def infer_with_hypotheses(context, gateway, *, registry):
    hypotheses = []

    class ProposalGateway:
        def propose(self, inputs):
            proposal = validate_proposal_v1(gateway.propose(inputs), inputs, registry)
            ordinary = []
            for suggestion in proposal["suggestions"]:
                ids = suggestion.get("fea_constraint_ids", [])
                if not ids:
                    ordinary.append(suggestion)
                    continue
                binding = suggestion["binding"]
                # Explicit/confirmed PI wins even when soft. No hypothesis can
                # fill a field the user already specified or marked indifferent.
                if any(c["target_id"] == suggestion["target_id"] and c["binding"]["domain"] == "PI"
                       and c["binding"]["feature"] == binding["feature"]
                       and c["binding"]["polarity"] in ("prefer", "require", "indifferent")
                       for c in context["constraints"]):
                    continue
                parents = [c for c in context["constraints"] if c["id"] in ids]
                refs = []
                for parent in parents:
                    for ref in parent["source_refs"]:
                        if ref not in refs:
                            refs.append(deepcopy(ref))
                fea = [deepcopy(c["binding"]) for c in parents]
                item = {"target_id": suggestion["target_id"], "binding": deepcopy(binding),
                        "fea": fea, "source_refs": refs, "reason": suggestion["reason"]}
                identity = {"target_id": item["target_id"], "binding": item["binding"],
                            "fea": sorted(fea, key=canonical), "source_refs": sorted(refs, key=canonical)}
                item["id"] = "hypothesis-" + hashlib.sha256(canonical(identity).encode()).hexdigest()[:32]
                hypotheses.append(item)
            return {"suggestions": ordinary, "questions": proposal["questions"]}

    target_map = infer_v1(context, ProposalGateway(), registry=registry)
    return target_map, hypotheses


def public_comparison(payload):
    """Expose only what the user is choosing, never internal evidence/DB data."""
    return {"candidate_set_ref": payload["candidate_set_ref"], "prompt": payload["prompt"],
            "options": [{"candidate_id": o["candidate_id"], "label": o["label"], "meaning": o["meaning"]}
                        for o in payload["options"]]}


def load_comparison(service, set_id):
    row = service._store.connection.execute("SELECT payload_json FROM consumer_comparisons WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        return None
    payload = json.loads(row[0])
    response = service._store.connection.execute("""SELECT f.payload_json FROM v1_feedback f
        JOIN v1_interpretations i ON json_extract(f.payload_json,'$.interpretation_ref.id')=i.id
        WHERE json_extract(f.payload_json,'$.candidate_set_ref.id')=?
        AND json_extract(i.payload_json,'$.status')='complete'
        AND json_extract(i.payload_json,'$.extraction_key') LIKE 'comparison-%' LIMIT 1""", (set_id,)).fetchone()
    payload["answered"] = response is not None
    return payload


def comparison_options(service, hypothesis, plan):
    feature = hypothesis["binding"]["feature"]
    cards = [card for card in plan["cards"] if card["target_id"] == hypothesis["target_id"] and card["image_id"]]
    options = []
    for card in cards:
        observation = next((a["observation"] for a in service._catalog.get_product_map(card["product_id"])["assertions"]
                            if a["status"] == "confirmed" and a["observation"].get("feature") == feature), None)
        if observation and observation["values"]:
            options.append({"candidate_id": card["candidate_id"], "values": observation["values"]})
    wanted = hypothesis["binding"]["values"][0]
    if not (any(wanted in o["values"] for o in options) and any(wanted not in o["values"] for o in options)):
        return []
    return options


def prepare_comparison(service, hypothesis, plan, round_obj):
    """Issue the exact option meanings before the user can see or accept them."""
    feature = hypothesis["binding"]["feature"]
    options = comparison_options(service, hypothesis, plan)
    if not options:
        return False
    request_id = round_obj["request_id"]
    snapshot = service._snapshot(request_id)
    sources = [ref for ref in hypothesis["source_refs"] if ref["type"] == "evidence"]
    if not sources:
        return False
    description = service.registry.describe()
    tags = []
    for fea in hypothesis["fea"]:
        tags.extend(t["label_ko"] for t in description["consumer_needs_taxonomy"][fea["category"]][fea["subcategory"]]
                    if t["attribute"] == fea["tag"])
    need = " · ".join(tags)
    feature_label = description["product_information"][feature]["label_ko"]
    basis = service._basis(snapshot) | {"catalog": plan["basis"]["catalog"]}
    subjects = sources + [round_obj["candidate_set_ref"], {"type": "round", "id": round_obj["id"], "version": round_obj["version"]}]
    for option in options:
        binding = deepcopy(hypothesis["binding"]) | {"values": option["values"]}
        label = f"{feature_label}: {', '.join(option['values'])}"
        meaning = {"kind": "preference", "content": f"이번 요청의 ‘{need}’ 요구에는 {label}를 선호한다.",
                   "fact": None, "selector": {"garment_type": next(t["garment_type"] for t in snapshot["request"]["targets"]
                                                                    if t["target_id"] == hypothesis["target_id"]),
                                               "slot_id": hypothesis["target_id"]},
                   "conditions": {}, "polarity": "prefer", "strength": "soft",
                   "valid_from": None, "valid_until": None, "scope": "short_term"}
        display = service._store.issue_display(service.user_id, request_id, purpose="confirm_content",
            snapshot={"meaning": meaning, "bindings": [binding], "subject_refs": subjects}, basis=basis)
        # These displays are rendered by the comparison, not the generic review list.
        service._store.connection.execute("INSERT OR IGNORE INTO consumer_dismissals VALUES (?)", (display["id"],))
        option.update(label=label, meaning=meaning["content"], display_ref={"type": "display", "id": display["id"], "version": display["version"]})
    payload = {"hypothesis_id": hypothesis["id"], "hypothesis": deepcopy(hypothesis), "candidate_set_ref": round_obj["candidate_set_ref"],
               "prompt": f"‘{need}’ 요구에는 어느 쪽 {feature_label}이 더 가까운가요?", "options": options,
               "sources": sources, "answered": False}
    service._store.connection.execute("INSERT INTO consumer_comparisons VALUES (?,?)",
                                      (round_obj["candidate_set_ref"]["id"], canonical(payload)))
    return True


def respond_comparison(service, snapshot, action, command, command_id):
    request_id = snapshot["request"]["id"]
    text = action.get("text")
    if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 4000):
        raise StyleMateError("invalid_input")
    batch_id = service._step(command_id, "comparison")
    prior = service._store.connection.execute("SELECT receipt_json FROM v1_batch_receipts WHERE user_id=? AND batch_id=?",
                                             (service.user_id, batch_id)).fetchone()
    if prior:
        if text is not None:
            service._extract(request_id, service._feedback_ref(json.loads(prior[0])), command_id)
        else:
            service._explore(request_id, service._step(command_id, "resume-comparison"))
        return
    c.validate_ref(action["candidate_set_ref"])
    active = next((r for r in snapshot["rounds"] if r["status"] == "active"), None)
    if active is None or active["candidate_set_ref"] != action["candidate_set_ref"]:
        raise StyleMateError("stale_context")
    payload = load_comparison(service, active["candidate_set_ref"]["id"])
    if payload is None or payload["answered"]:
        raise StyleMateError("stale_context")
    option = next((o for o in payload["options"] if o["candidate_id"] == action["candidate_id"]), None)
    choosing = action["decision"] == "choose"
    if (choosing and option is None) or (not choosing and action["candidate_id"] is not None):
        raise StyleMateError("invalid_input")
    service._store._v1.feedback.current_set(service._store._request_row(service.user_id, request_id), active["id"],
        active["candidate_set_ref"]["id"], command["expected"], service._store._now(), service._catalog)
    selection = next((card for s in snapshot["candidate_sets"] if s["id"] == active["candidate_set_ref"]["id"]
                      for card in s["cards"] if option and card["candidate_id"] == option["candidate_id"]), None)
    feedback = {"op": "submit_feedback", "round_id": active["id"], "candidate_set_id": active["candidate_set_ref"]["id"],
                "reaction": "selected" if choosing else "none" if action["decision"] == "neither" else "unsure",
                "selections": [{"target_id": selection["target_id"], "candidate_id": selection["candidate_id"], "part_ref": None}] if choosing else [],
                "text": text, "question_id": None}
    response = {"op": "record_comparison", "feedback": feedback, "memory": None, "source_refs": [], "bindings": [], "confirmation_event_ref": None}
    if choosing and text is None:
        event = service._store.record_user_event(service.user_id, request_id, command_id=command_id,
            display_ref=option["display_ref"], purpose="confirm_content", expected=command["expected"])
        display = service._store._v1._resolve(service.user_id, request_id, option["display_ref"], service._store._now())
        response.update({"memory": {k: display["snapshot"]["meaning"][k] for k in c.MemoryContent.__required_keys__},
                        "source_refs": payload["sources"], "bindings": display["snapshot"]["bindings"],
                        "confirmation_event_ref": event})
    receipt = service._apply(request_id, batch_id, [response], command["expected"])
    if text is not None:
        # Interpret the choice and actual explanation together. A correction
        # may contradict the staged PI, so do not silently confirm that PI.
        service._extract(request_id, service._feedback_ref(receipt), command_id)
    else:
        service._explore(request_id, command_id)
