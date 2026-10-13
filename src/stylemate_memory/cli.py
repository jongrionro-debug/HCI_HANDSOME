"""Local JSON/CLI boundary. Demo and default inference never call a network."""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from .app import ShoppingApp
from .errors import StyleMateError
from .inference import RuleAdapter
from .registry import FEATURES, registry_metadata
from .store import MemoryStore


def configured_adapter(provider: str, model: str | None, settings: dict[str, str]) -> Any:
    """Explicit future-call configuration; test with a supplied dummy mapping."""
    if provider == "rule":
        return RuleAdapter()
    if provider != "openai":
        raise StyleMateError("invalid_provider", "지원하는 연결 방식은 rule 또는 openai입니다.")
    from .llm import OpenAIResponsesAdapter

    model_name = model or settings.get("STYLEMATE_OPENAI_MODEL", "")
    api_key = settings.get("OPENAI_API_KEY", "")
    return OpenAIResponsesAdapter(model=model_name, api_key=api_key)


def _draft(feature: str, values: list[str | int], *, scope: str = "short_term", **extra: Any) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "op": "create",
        "feature": feature,
        "values": values,
        "scope": scope,
        "polarity": "prefer",
        "strength": "soft",
        "confirmed": True,
        "evidence_ref": f"synthetic-user-input:{feature}:{scope}",
        "content": f"가상 사용자가 확인한 {feature}: {values}",
        "selector": {"garment_type": "Pants"},
    }
    if scope == "long_term":
        draft["consent_ref"] = f"synthetic-future-use-consent:{feature}"
    draft.update(extra)
    return draft


def synthetic_demo() -> dict[str, Any]:
    """Exercise long-term preference, today's exception, and the next request."""
    with tempfile.TemporaryDirectory(prefix="stylemate-demo-") as folder:
        with MemoryStore(Path(folder) / "memory.sqlite3") as store:
            user_id = "synthetic-shopper"
            base = store.start_request(user_id, input_id="demo-base", text="평소 취향 설정", timezone="Asia/Seoul")
            store.apply_batch(
                user_id, base["id"], batch_id="demo-save-base",
                actions=[_draft("fit", ["Relaxed"], scope="long_term"), _draft("color", ["Navy"], scope="long_term")],
            )
            current = store.start_request(user_id, input_id="demo-meeting", text="오늘 미팅에 입을 바지", timezone="Asia/Seoul")
            local = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul"))
            until = datetime.combine(local.date() + timedelta(days=1), time.min, ZoneInfo("Asia/Seoul"))
            store.apply_batch(
                user_id, current["id"], batch_id="demo-today-only",
                actions=[
                    _draft("fit", ["Slim"], valid_until=until.astimezone(timezone.utc).isoformat()),
                    _draft("goal", ["smart casual"], selector={}, content="가상 사용자가 단정한 쇼핑 목표를 확인"),
                ],
            )
            app = ShoppingApp(store, RuleAdapter())
            targets = [{"id": "pants-1", "garment_type": "Pants"}]
            before = store.snapshot(user_id, current["id"])
            today = app.infer_request(user_id, current["id"], targets)
            after = store.snapshot(user_id, current["id"])
            following = store.start_request(user_id, input_id="demo-next", text="다음 쇼핑 요청", timezone="Asia/Seoul")
            next_profile = app.infer_request(user_id, following["id"], targets)
            return {
                "synthetic": True,
                "provider": "offline-rule-fixture",
                "feature_count": len(FEATURES),
                "today": today,
                "next_request": next_profile,
                "memory_unchanged_by_inference": before["memories"] == after["memories"] and before["profile_revision"] == after["profile_revision"],
                "live_llm_called": False,
            }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StyleMate 쇼핑 메모리·목표 feature 로컬 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="가상 사용자로 오늘 예외와 다음 요청을 시연")
    demo.add_argument("--synthetic", action="store_true", required=True)
    sub.add_parser("features", help="소비자용 feature 사전 출력")
    for name in ("request", "batch", "infer"):
        command = sub.add_parser(name)
        command.add_argument("--db", required=True, help="저장소 밖의 로컬 SQLite 경로")
        command.add_argument("--user", required=True, help="신뢰된 로컬 호출자의 사용자 ID")
        if name == "request":
            command.add_argument("--input-id", required=True)
            command.add_argument("--text", required=True)
            command.add_argument("--timezone", required=True)
        else:
            command.add_argument("--request", required=True)
        if name == "batch":
            command.add_argument("--batch-id", required=True)
            command.add_argument("--actions-file", required=True)
        if name == "infer":
            command.add_argument("--targets-file", required=True)
            command.add_argument("--provider", choices=("rule", "openai"), default="rule")
            command.add_argument("--model")
    return parser


def _read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise StyleMateError("invalid_input_file", "입력 JSON 파일을 읽을 수 없습니다.") from None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "features":
            result = registry_metadata()
        elif args.command == "demo":
            result = synthetic_demo()
        else:
            # Credentials are read only for an explicit future openai command,
            # never during imports, demos, rule inference, or ordinary tests.
            adapter = None
            if args.command == "infer":
                settings = {}
                if args.provider == "openai":
                    settings = {
                        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                        "STYLEMATE_OPENAI_MODEL": os.environ.get("STYLEMATE_OPENAI_MODEL", ""),
                    }
                adapter = configured_adapter(args.provider, args.model, settings)
            with MemoryStore(args.db) as store:
                if args.command == "request":
                    result = store.start_request(args.user, input_id=args.input_id, text=args.text, timezone=args.timezone)
                elif args.command == "batch":
                    result = store.apply_batch(args.user, args.request, batch_id=args.batch_id, actions=_read_json(args.actions_file))
                else:
                    result = ShoppingApp(store, adapter).infer_request(args.user, args.request, _read_json(args.targets_file))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except StyleMateError as error:
        print(json.dumps({"error": error.as_dict()}, ensure_ascii=False))
        return 2
    except (OSError, TypeError, ValueError):
        print(json.dumps({"error": {"code": "invalid_input", "message": "입력 또는 로컬 저장 경로를 확인해 주세요."}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
