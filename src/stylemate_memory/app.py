"""Connect an owned store snapshot to a read-only inference adapter."""

from __future__ import annotations

from typing import Any

from .context import build_context
from .errors import StyleMateError
from .inference import ModelAdapter, infer


class ShoppingApp:
    """The caller supplies a trusted local user ID; this is not authentication."""

    def __init__(self, store: Any, adapter: ModelAdapter) -> None:
        self.store = store
        self.adapter = adapter

    def infer_request(
        self,
        user_id: str,
        request_id: str,
        targets: list[dict[str, Any]],
        *,
        facts: dict[str, Any] | None = None,
        char_budget: int = 6000,
    ) -> dict[str, Any]:
        snapshot = self.store.snapshot(user_id, request_id)
        context = build_context(
            snapshot,
            targets,
            facts=facts,
            char_budget=char_budget,
        )
        if context.get("blocked"):
            raise StyleMateError("context_blocked", "필수 조건을 유지할 수 없어 추론을 보류했습니다.")
        profile = infer(context, self.adapter)
        try:
            current = build_context(
                self.store.snapshot(user_id, request_id),
                targets,
                facts=facts,
                char_budget=char_budget,
            )
        except StyleMateError:
            raise StyleMateError("stale_context", "요청이나 기억이 변경되어 결과를 다시 만들어야 합니다.") from None
        if current.get("blocked") or current.get("context_id") != context.get("context_id"):
            raise StyleMateError("stale_context", "요청이나 기억이 변경되어 결과를 다시 만들어야 합니다.")
        used_ids = {
            source_id
            for item in profile.get("suggestions", []) + profile.get("constraints", [])
            for source_id in item.get("source_ids", [])
        }
        profile["request_id"] = request_id
        profile["versions"] = {
            "request": snapshot["request"]["revision"],
            "profile": snapshot["profile_revision"],
            "memories": {
                memory["id"]: memory["version"]
                for memory in snapshot["memories"]
                if memory["id"] in used_ids
            },
        }
        return profile
