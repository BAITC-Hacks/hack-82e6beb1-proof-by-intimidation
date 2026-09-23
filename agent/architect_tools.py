"""Deterministic, source-bound tools for the briefing analyst.

The model assesses meaning; these tools own evidence checks and arithmetic.
The published score is applied by the server only after human confirmation.
"""

from __future__ import annotations

import re
from typing import Any

from agent.evidence import original_quote

FIELDS = (
    "title", "context", "need", "users", "data", "constraints",
    "expected_result", "success_criteria", "contact", "interaction_format",
)
RUBRIC = {
    "context": {"weight": 20, "fields": ("context", "need"), "labels": ("Контекст и потребность", "Мәселе мен қажеттілік", "Problem and context"), "complete": "Affected process, current pain and desired change are concrete and distinguishable."},
    "data": {"weight": 20, "fields": ("data",), "labels": ("Данные и материалы", "Деректер мен материалдар", "Data and materials"), "complete": "Specific source/materials, format or examples, availability and a realistic access path are stated. Explicitly justified no-data work can qualify."},
    "expected_result": {"weight": 15, "fields": ("expected_result",), "labels": ("Ожидаемый результат", "Күтілетін нәтиже", "Expected deliverable"), "complete": "A bounded deliverable states what the team hands over and what it must do. Do not invent a technology choice."},
    "success_criteria": {"weight": 15, "fields": ("success_criteria",), "labels": ("Критерии успеха", "Табыс өлшемдері", "Success criteria"), "complete": "Observable acceptance conditions and how business will check them are explicit; quantitative thresholds where appropriate, qualitative tests are also valid."},
    "constraints": {"weight": 10, "fields": ("constraints",), "labels": ("Ограничения", "Шектеулер", "Scope and constraints"), "complete": "Applicable time, scope, access, cost or privacy constraints are concrete; explicit absence of a constraint is a valid fact."},
    "users": {"weight": 10, "fields": ("users",), "labels": ("Пользователи", "Пайдаланушылар", "People using the result"), "complete": "A specific user group and the action/job they need to accomplish are stated, without unnecessary sensitive attributes."},
    "contact": {"weight": 10, "fields": ("contact", "interaction_format"), "labels": ("Связь с бизнесом", "Бизнеспен байланыс", "Business collaboration"), "complete": "A usable business contact/channel and an agreed feedback format/cadence are explicit."},
}
LANG_INDEX = {"ru": 0, "kk": 1, "en": 2}
READINESS = {
    "ru": ("Черновик", "Рабочая", "Готовая", "Приоритетная"),
    "kk": ("Бастапқы", "Жұмысқа жарамды", "Дайын", "Басым"),
    "en": ("Draft", "Developing", "Ready", "Priority"),
}
_PLACEHOLDERS = {"", "нет данных", "не знаю", "неизвестно", "уточним", "потом", "n/a", "tbd", "unknown", "not sure", "i don't know", "белгісіз", "білмеймін", "кейін", "-", "?"}


def has_information(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in _PLACEHOLDERS and bool(re.search(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9]", value))


def source_for(fields: dict[str, Any], criterion: str) -> str:
    values = [str(fields.get(key, "")).strip() for key in RUBRIC[criterion]["fields"] if fields.get(key)]
    return "\n".join(dict.fromkeys(values)).strip()


def get_rubric(language: str = "ru") -> dict[str, Any]:
    idx = LANG_INDEX.get(language, 0)
    return {
        "criteria": [{"key": key, "label": rule["labels"][idx], "weight": rule["weight"], "fields": list(rule["fields"]), "complete_requires": rule["complete"]} for key, rule in RUBRIC.items()],
        "levels": {"0": "Absent, irrelevant, contradictory or explicit unknown.", "1": "Relevant mention, too vague to act on.", "2": "Specific useful information, with a major practical gap.", "3": "Actionable; a minor clarification remains.", "4": "Complete enough to begin work and verify the result for this criterion."},
        "formula": "points = floor(weight * level / 4 + 0.5); total = sum(points). No text-length bonus. Human confirmation is required before publishing points.",
    }


def verify_quotes(claims: list[dict[str, str]], sources: dict[str, str], max_claims: int = 2048) -> dict[str, Any]:
    """Source text comes from the server, never from model-supplied tool arguments."""
    if not isinstance(claims, list) or len(claims) > max_claims or any(not isinstance(item, dict) for item in claims):
        return {"valid": False, "checks": []}
    checks = []
    for claim in claims:
        source, quote = claim.get("source", ""), claim.get("quote", "")
        field = claim.get("field", "")
        allowed = isinstance(source, str) and (source == "draft" or (source.startswith("answers.") and source[8:] in FIELDS))
        if quote == "" and allowed and field in FIELDS:
            continue  # An empty field makes no factual claim to verify.
        matched = original_quote(quote, sources.get(source, "")) if allowed and isinstance(quote, str) else None
        valid = bool(allowed and field in FIELDS and matched)
        checks.append({"field": field, "source": source, "quote": matched or quote, "valid": valid})
    return {"valid": all(item["valid"] for item in checks), "checks": checks}


def score_card_fields(fields: dict[str, Any], review: list[dict[str, Any]] | None = None, language: str = "ru") -> dict[str, Any]:
    """Compute a preview, or a confirmed rating when called after confirmation.

    Semantic levels are accepted only with evidence in the corresponding field.
    Without a review we report conservative presence credit, never claim AI quality.
    Caller must not accept review/levels from untrusted browser request bodies.
    """
    language = language if language in LANG_INDEX else "ru"
    index = LANG_INDEX[language]
    reviews = {item.get("key"): item for item in (review or []) if isinstance(item, dict)}
    criteria = []
    for key, rule in RUBRIC.items():
        source = source_for(fields, key)
        present = [has_information(fields.get(field)) for field in rule["fields"]]
        candidate = reviews.get(key, {})
        quote = candidate.get("evidence", "")
        level = candidate.get("level")
        valid = isinstance(quote, str) and (bool(quote) or level == 0) and (not quote or quote in source) and isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 4
        if valid:
            level = level if any(present) else 0
            cap_message = ""
            # Both halves of compound criteria are required for full readiness.
            if not all(present):
                if level > 2:
                    cap_message = (
                        "Для полной оценки нужны обе части: " + ("текущая ситуация и желаемое изменение." if key == "context" else "контакт и формат обратной связи."),
                        "Толық бағалау үшін екі бөлік те қажет: " + ("қазіргі жағдай және қалаған өзгеріс." if key == "context" else "байланыс және кері байланыс форматы."),
                        "Full credit needs both " + ("the current situation and desired change." if key == "context" else "a contact and feedback format."),
                    )[index]
                level = min(level, 2)
            reason = cap_message or str(candidate.get("reason", "")).strip()
            next_step = cap_message or str(candidate.get("next_step", "")).strip()
            evidence = quote
        else:
            level = 1 if any(present) else 0
            reason = (
                "Информация добавлена. Смысловая полнота пока не проверена AI." if level else "Сведения ещё не указаны.",
                "Ақпарат қосылды. Мағыналық толықтығын AI әлі тексерген жоқ." if level else "Ақпарат әлі берілмеген.",
                "Information supplied. Semantic completeness has not been reviewed by AI." if level else "Information has not been supplied yet.",
            )[index]
            next_step = (
                "Уточните поле и запустите AI-проверку.",
                "Өрісті нақтылап, AI тексеруін іске қосыңыз.",
                "Clarify this field and run the AI review.",
            )[index]
            evidence = source if level else ""
        points = (rule["weight"] * level + 2) // 4
        criteria.append({"key": key, "label": rule["labels"][index], "weight": rule["weight"], "level": level, "points": points, "evidence": evidence, "reason": reason, "next_step": next_step})
    score = sum(item["points"] for item in criteria)
    band = 0 if score < 40 else 1 if score < 70 else 2 if score < 90 else 3
    return {"criteria": criteria, "score": score, "readiness": READINESS[language][band]}


def compare_revision(current: dict[str, str], previous: dict[str, str]) -> dict[str, Any]:
    changes = [{"field": key, "before": previous.get(key, ""), "after": current.get(key, "")} for key in FIELDS if current.get(key, "") != previous.get(key, "")]
    return {"changed_fields": changes, "note": "Changes are supplied information, not confirmed facts or guaranteed score increases."}


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
FIELD_SCHEMA = object_schema({key: STRING for key in FIELDS})
REVIEW_SCHEMA = object_schema({"key": {"type": "string", "enum": list(RUBRIC)}, "level": {"type": "integer", "minimum": 0, "maximum": 4}, "evidence": STRING, "reason": STRING, "next_step": STRING})
EVIDENCE_SCHEMA = object_schema({"field": {"type": "string", "enum": list(FIELDS)}, "quote": STRING, "source": STRING})
TOOL_SCHEMAS = [
    {"type": "function", "name": "get_readiness_rubric", "description": "Get the authoritative seven criteria, weights and semantic levels before assessing this brief.", "strict": True, "parameters": object_schema({})},
    {"type": "function", "name": "verify_user_evidence", "description": "Verify original passages in the user draft or any supplied answer. Whitespace may vary; words must not. Source must be draft or answers.FIELD. Verify separate passages separately; never supply source contents.", "strict": True, "parameters": object_schema({"claims": {"type": "array", "items": EVIDENCE_SCHEMA}})},
    {"type": "function", "name": "calculate_readiness", "description": "Calculate preview points using proposed semantic levels and source-grounded fields. This does not confirm or publish the card.", "strict": True, "parameters": object_schema({"fields": FIELD_SCHEMA, "criteria": {"type": "array", "items": REVIEW_SCHEMA}})},
    {"type": "function", "name": "compare_revision", "description": "Compare fields extracted from the original draft with the updated fields after answers. Both versions must contain only exact source excerpts. Useful after clarification.", "strict": True, "parameters": object_schema({"previous_fields": FIELD_SCHEMA, "fields": FIELD_SCHEMA})},
]
