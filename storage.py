"""Small local JSON store; no external services required."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNTIME_FILE = DATA_DIR / "runtime.json"


def _read_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _seed_state() -> dict[str, list[dict[str, Any]]]:
    return {
        "tasks": _read_json(DATA_DIR / "tasks.json"),
        "teams": _read_json(DATA_DIR / "teams.json"),
        "proposals": _read_json(DATA_DIR / "proposals.json"),
        "progress": [],
    }


def load_drafts() -> list[dict[str, Any]]:
    return _read_json(DATA_DIR / "drafts.json")


def load_demo_card(card_id: str) -> dict[str, Any]:
    return next((item for item in _read_json(DATA_DIR / "tasks.json") if item["id"] == card_id), {})


def load_state() -> dict[str, list[dict[str, Any]]]:
    if RUNTIME_FILE.exists():
        return _read_json(RUNTIME_FILE)
    return deepcopy(_seed_state())


def save_state(state: dict[str, list[ dict[str, Any] ]]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with RUNTIME_FILE.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def reset_state() -> dict[str, list[dict[str, Any]]]:
    state = _seed_state()
    save_state(state)
    return state


def next_id(items: list[dict[str, Any]], prefix: str) -> str:
    numbers = [int(str(item.get("id", "")).removeprefix(prefix) or 0) for item in items if str(item.get("id", "")).removeprefix(prefix).isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"
