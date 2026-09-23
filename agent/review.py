"""AI quality review with local evidence validation."""

from __future__ import annotations

import json
from typing import Any

from agent.prompts import QUALITY_REVIEW_PROMPT
from rating import SCORING_RULES

_ITEM = {
    "type": "object",
    "properties": {
        "level": {"type": "integer"}, "evidence": {"type": "string"},
        "reason": {"type": "string"}, "next_step": {"type": "string"},
    },
    "required": ["level", "evidence", "reason", "next_step"],
    "additionalProperties": False,
}
_SCHEMA = {
    "type": "object",
    "properties": {"criteria": {"type": "object", "properties": {key: _ITEM for key in SCORING_RULES}, "required": list(SCORING_RULES), "additionalProperties": False}},
    "required": ["criteria"], "additionalProperties": False,
}


def _evidence_source(payload: dict[str, str], key: str, draft: bool) -> str:
    if draft:
        return payload.get("draft", "")
    if key == "context":
        return f"{payload.get('context', '')}\n{payload.get('need', '')}"
    return payload.get(key, "")


def validate_review(raw: Any, payload: dict[str, str], draft: bool = False) -> dict[str, dict[str, Any]]:
    """Discard unsupported claims; never let a model invent evidence for a score."""
    criteria = raw.get("criteria", {}) if isinstance(raw, dict) else {}
    validated = {}
    for key in SCORING_RULES:
        item = criteria.get(key, {}) if isinstance(criteria, dict) else {}
        if not isinstance(item, dict): item = {}
        evidence = str(item.get("evidence") or "").strip()
        source = _evidence_source(payload, key, draft)
        try: level = max(0, min(4, int(item.get("level", 0))))
        except (ValueError, TypeError): level = 0
        if not evidence or evidence.casefold() not in source.casefold():
            level, evidence = 0, ""
        validated[key] = {
            "level": level, "evidence": evidence,
            "reason": str(item.get("reason") or "").strip()[:240],
            "next_step": str(item.get("next_step") or "").strip()[:240],
        }
    return validated


def review_quality(client: Any, model: str, payload: dict[str, str], draft: bool = False) -> dict[str, dict[str, Any]]:
    response = client.responses.create(
        model=model,
        instructions=QUALITY_REVIEW_PROMPT,
        input=json.dumps({"stage": "draft" if draft else "card", "facts": payload}, ensure_ascii=False),
        text={"format": {"type": "json_schema", "name": "quality_review", "strict": True, "schema": _SCHEMA}},
    )
    raw = json.loads(response.output_text)
    return validate_review(raw, payload, draft=draft)
