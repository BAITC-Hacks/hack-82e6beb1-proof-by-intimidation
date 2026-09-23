"""Deterministic readiness scoring for business tasks."""

from __future__ import annotations

from typing import Any

SCORING_RULES = {
    "context": ("Контекст и потребность", 20),
    "data": ("Данные и материалы", 20),
    "expected_result": ("Ожидаемый результат", 15),
    "success_criteria": ("Критерии успеха", 15),
    "constraints": ("Ограничения", 10),
    "users": ("Пользователи", 10),
    "contact": ("Связь с бизнесом", 5),
    "interaction_format": ("Формат взаимодействия", 5),
}

CARD_FIELDS = {
    "title": "Название",
    "context": "Контекст",
    "need": "Потребность",
    "users": "Пользователи",
    "data": "Данные",
    "constraints": "Ограничения",
    "expected_result": "Ожидаемый результат",
    "success_criteria": "Критерии успеха",
    "contact": "Контакт",
    "interaction_format": "Формат взаимодействия",
}


def is_filled(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) >= 3


def readiness_level(score: int) -> str:
    if score < 40:
        return "Черновик"
    if score < 70:
        return "Рабочая"
    if score < 90:
        return "Готовая"
    return "Приоритетная"


def calculate_rating(card: dict[str, Any]) -> dict[str, Any]:
    """Return an explainable 0-100 rating. Only confirmed, non-empty fields score."""
    confirmed = set(card.get("confirmed_fields", []))
    breakdown: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0

    for key, (label, points) in SCORING_RULES.items():
        has_value = is_filled(card.get(key))
        # Context and need jointly describe the first 20-point criterion.
        if key == "context":
            has_value = has_value and is_filled(card.get("need"))
            confirmed_for_score = {"context", "need"}.issubset(confirmed)
        else:
            confirmed_for_score = key in confirmed
        earned = points if has_value and confirmed_for_score else 0
        score += earned
        breakdown.append({"field": label, "max": points, "earned": earned})
        if not has_value:
            missing.append(label)

    improvements = [f"Добавьте «{item['field']}»: до +{item['max']} баллов." for item in breakdown if item["earned"] == 0]
    return {
        "score": score,
        "level": readiness_level(score),
        "breakdown": breakdown,
        "missing": missing,
        "improvements": improvements,
    }
