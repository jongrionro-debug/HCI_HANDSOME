"""Closed, versioned situation dictionary (ADR 0013 decision 11).

Request situations are facts, not conditions. A model maps each one to a
dictionary value or ``기타``; ``기타`` keeps the raw wording but never matches.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json
from typing import Any

SITUATION_KEYS = ("occasion", "season", "activity")


@lru_cache(maxsize=1)
def situation_dictionary() -> dict[str, Any]:
    text = resources.files("stylemate_memory").joinpath("resources/situation-dictionary-v1.json").read_text("utf-8")
    data = json.loads(text)
    if tuple(data["keys"]) != SITUATION_KEYS:
        raise ValueError("situation dictionary keys changed")
    return data


def other_value() -> str:
    return situation_dictionary()["other"]


def allowed_values(key: str) -> tuple[str, ...]:
    return tuple(situation_dictionary()["keys"][key]) + (other_value(),)


def matchable(item: dict[str, Any]) -> bool:
    """Only dictionary values match across requests; ``기타`` never does."""
    return item["value"] != other_value()
