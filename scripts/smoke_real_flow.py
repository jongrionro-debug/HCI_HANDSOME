#!/usr/bin/env python3
"""Run fixed Korean shopping requests through ConsumerService and record each step.

The script is an end-to-end smoke check, not a quality benchmark. Every scenario
starts a new request, accepts each extracted memory's content and binding review
(as a cooperating tester would), explores once, and ends the request. It records
the extracted wording/bindings, operation state, card count and PI values, and
any FEA->PI comparison. Use ``--provider fake`` for a call-free plumbing run;
``--provider opencode-go`` makes real DeepSeek calls and must be requested.

    python3 scripts/smoke_real_flow.py --catalog "$DATA/lumi-catalog-complete-v1.jsonl" \
        --image-root "$DATA/images" --registry lumi-29cm-v1 --provider opencode-go \
        --output "$DATA/smoke_real_flow.json"
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stylemate_memory import contracts as c  # noqa: E402
from stylemate_memory.app import ConsumerService  # noqa: E402
from stylemate_memory.errors import StyleMateError  # noqa: E402
from stylemate_memory.llm import create_model_gateway  # noqa: E402
from stylemate_memory.registry import load_registry  # noqa: E402
from stylemate_memory.settings import DEEPSEEK_DEFAULT_MODEL  # noqa: E402

ENDPOINT = "https://opencode.ai/inference/go/openai/v1/chat/completions"
SCENARIOS = [
    ("Pants", "회사 발표 때 입을 단정한 검정 슬랙스를 찾고 있어요."),
    ("Pants", "주말에 편하게 입을 바지가 필요해요."),
    ("Pants", "청바지 말고 베이지나 카키색 코튼 팬츠로 보여주세요."),
    ("Knit/Sweater", "울 소재 네이비 니트인데 너무 붙지 않는 핏이면 좋겠어요."),
    ("T-shirt", "여름에 입을 흰색 반팔 티셔츠, 오버핏으로요."),
    ("Skirt", "데이트할 때 입을 롱 스커트를 찾아요."),
    ("Shirt", "스트라이프 셔츠 찾아요. 너무 비싸지 않았으면 해요."),
    ("Hoodie", "따뜻하게 입을 회색 후디요."),
]


def trace_gateway(gateway: Any, log: list[dict[str, Any]]) -> None:
    """Record raw model JSON and validation errors per call (``--trace``; output stays outside the repo)."""
    complete = gateway.complete

    def traced_complete(instructions: str, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        entry = {"call": instructions.split(" ", 1)[0], "started": round(time.monotonic(), 1)}
        log.append(entry)
        try:
            entry["output"] = complete(instructions, payload, schema)
            return entry["output"]
        except Exception as error:  # noqa: BLE001 - diagnostic record only
            entry["error"] = [getattr(error, "code", type(error).__name__), str(error)[:300]]
            raise

    def wrap(name: str) -> None:
        original = getattr(gateway, name)

        def traced(inputs: Any) -> Any:
            try:
                return original(inputs)
            except Exception as error:  # noqa: BLE001
                log.append({"call": name, "validation_error": [getattr(error, "code", type(error).__name__), str(error)[:300]]})
                raise
        setattr(gateway, name, traced)

    gateway.complete = traced_complete
    for name in ("extract", "propose"):
        wrap(name)


class Runner:
    def __init__(self, service: ConsumerService, wait_s: float) -> None:
        self.service, self.wait_s, self.serial = service, wait_s, 0

    def send(self, action: dict[str, Any], *, start: bool = False) -> dict[str, Any]:
        state = self.service.state()
        self.serial += 1
        result = self.service.command({
            "contract_version": c.CONTRACT_VERSION, "command_id": f"smoke-{self.serial}",
            "request_id": None if start else state["request"]["id"],
            "expected": None if start else state["expected"], "action": action})
        self.service.wait_idle(self.wait_s)
        if result["outcome"] == "rejected":
            raise StyleMateError((result["error"] or {}).get("code", "rejected"), "command rejected")
        return self.service.state()

    def review(self, purpose: str, memory: dict[str, Any]) -> None:
        self.send({"op": "prepare_review", "purpose": purpose, "subject_refs": [memory["ref"]], "proposed_text": None})
        reviews = self.service.state()["reviews"]
        if not reviews:
            raise StyleMateError("no_review", "review was not issued")
        self.send({"op": "respond_review", "display_ref": reviews[0]["ref"], "decision": "accept"})


def _bindings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for binding in snapshot.get("bindings", []):
        spec = binding.get("binding", binding)
        out.append({k: spec.get(k) for k in ("domain", "feature", "values", "category", "subcategory", "tag",
                                              "polarity", "strength") if spec.get(k) is not None}
                   | {"confirmed": binding.get("confirmed")})
    return out


def run_scenario(runner: Runner, garment: str, text: str, trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"garment_type": garment, "text": text, "steps": []}
    if trace is not None:
        trace.clear()
    started = time.monotonic()
    try:
        state = runner.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                             "targets": [{"target_id": "item-1", "garment_type": garment}], "text": text}, start=True)
        row["steps"].append(["start", state["operation"]])
        row["memories"] = [m["content"] for m in state["memories"]]
        for memory in list(state["memories"]):
            for purpose in ("confirm_content", "confirm_bindings"):
                if purpose == "confirm_bindings" and not any(
                        b["memory_id"] == memory["ref"]["id"] and b["status"] in ("candidate", "active")
                        for b in runner.service.inspect_request(state["request"]["id"])["snapshot"]["bindings"]):
                    row["steps"].append([purpose, "no_bindings"])
                    continue
                try:
                    runner.review(purpose, next(m for m in runner.service.state()["memories"]
                                                if m["ref"]["id"] == memory["ref"]["id"]))
                    row["steps"].append([purpose, "accepted"])
                except (StyleMateError, StopIteration) as error:
                    row["steps"].append([purpose, getattr(error, "code", "missing")])
        state = runner.service.state()
        snapshot = runner.service.inspect_request(state["request"]["id"])["snapshot"]
        row["bindings"] = _bindings(snapshot)
        state = runner.send({"op": "explore"})
        row["steps"].append(["explore", state["operation"]])
        row["error"] = state["error"]
        if state["operation"] == "blocked":
            context = runner.service.inspect_request(state["request"]["id"])["context"]
            row["blocked_reasons"] = context["questions"] if context else None
        row["cards"] = [{"title": card["title"], "image": bool(card["image_url"]),
                         "facts": {f["feature"]: f["values"] for f in card.get("facts", [])}} for card in state["cards"]]
        comparison = state.get("comparison")
        row["comparison"] = None if not comparison else {
            "prompt": comparison["prompt"], "options": [o["label"] for o in comparison["options"]]}
        row["questions"] = [q["text"] for q in state["questions"]]
        runner.send({"op": "end_request"})
    except (StyleMateError, TimeoutError) as error:
        row["failure"] = getattr(error, "code", type(error).__name__)
    row["elapsed_s"] = round(time.monotonic() - started, 1)
    if trace is not None:
        row["trace"] = list(trace)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", required=True, help="lumi-catalog-v1 JSONL (outside the repository)")
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--registry", default="lumi-29cm-v1")
    parser.add_argument("--provider", choices=("fake", "opencode-go"), default="fake")
    parser.add_argument("--model", default=DEEPSEEK_DEFAULT_MODEL)
    parser.add_argument("--output", required=True, help="result JSON (outside the repository)")
    parser.add_argument("--wait-s", type=float, default=120)
    parser.add_argument("--only", type=int, nargs="*", help="scenario indexes to run")
    parser.add_argument("--trace", action="store_true", help="record raw model JSON and validation errors per scenario")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    paths = [Path(p).expanduser().resolve() for p in (args.catalog, args.image_root, args.output)]
    if any(p.is_relative_to(repo) for p in paths):
        print("데이터와 출력 경로는 저장소 밖이어야 합니다.", file=sys.stderr)
        return 2
    if args.provider == "opencode-go":
        key = os.environ.get("OPENCODE_API_KEY", "")
        if not key.strip():
            print("OPENCODE_API_KEY가 설정되지 않아 중단합니다(다른 provider로 대체하지 않음).", file=sys.stderr)
            return 3
        gateway = create_model_gateway("opencode-go", model=args.model, api_key=key, endpoint=ENDPOINT)
    else:
        gateway = create_model_gateway("fake")
    trace: list[dict[str, Any]] | None = [] if args.trace else None
    if trace is not None:
        trace_gateway(gateway, trace)
    scenarios = [s for i, s in enumerate(SCENARIOS) if not args.only or i in args.only]
    with tempfile.TemporaryDirectory(prefix="lumi-smoke-") as temp:
        service = ConsumerService(Path(temp) / "memory.sqlite3", Path(temp) / "catalog.sqlite3", gateway,
                                  user_id="smoke-tester", image_root=paths[1], registry=load_registry(args.registry))
        try:
            service.import_catalog(paths[0])
            service.build_catalog_maps()
            runner = Runner(service, args.wait_s)
            rows = []
            for garment, text in scenarios:
                rows.append(run_scenario(runner, garment, text, trace))
                print(json.dumps({k: rows[-1].get(k) for k in ("garment_type", "steps", "failure", "elapsed_s")},
                                 ensure_ascii=False), file=sys.stderr)
        finally:
            service.close()
    summary = {
        "provider": args.provider, "model": args.model if args.provider != "fake" else None,
        "registry": args.registry, "scenarios": len(rows),
        "with_bindings": sum(bool(r.get("bindings")) for r in rows),
        "with_cards": sum(bool(r.get("cards")) for r in rows),
        "with_comparison": sum(bool(r.get("comparison")) for r in rows),
        "failures": sum("failure" in r for r in rows),
    }
    paths[2].write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
