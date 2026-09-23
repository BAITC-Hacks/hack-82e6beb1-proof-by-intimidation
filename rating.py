"""Evidence-backed readiness scoring for business tasks."""

from __future__ import annotations

import re
from typing import Any

SCORING_RULES = {
    "context": ("Контекст и потребность", 20),
    "data": ("Данные и материалы", 20),
    "expected_result": ("Ожидаемый результат", 15),
    "success_criteria": ("Критерии успеха", 15),
    "constraints": ("Ограничения", 10),
    "users": ("Пользователи", 10),
    "contact": ("Контакт", 5),
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


NEXT_STEPS = {
    "context": "Укажите, кто сталкивается с проблемой, на каком шаге и что сейчас происходит.",
    "data": "Назовите источник, формат, объём и способ доступа к данным или примерам.",
    "expected_result": "Опишите проверяемый артефакт, который команда передаст в конце.",
    "success_criteria": "Добавьте измеримый показатель, порог и способ проверки результата.",
    "constraints": "Укажите сроки, ограничения доступа и правила работы.",
    "users": "Назовите конкретную группу пользователей и её задачу.",
    "contact": "Оставьте рабочий канал связи с представителем бизнеса.",
    "interaction_format": "Укажите канал, частоту и формат обратной связи команде.",
}


def _source(card: dict[str, Any], key: str) -> str:
    if key == "context":
        return f"{card.get('context') or ''}\n{card.get('need') or ''}".strip()
    return str(card.get(key) or "").strip()


def _local_level(key: str, source: str, card: dict[str, Any]) -> int:
    """Conservative fallback, never presented as an AI assessment."""
    if not is_filled(source): return 0
    if key == "context" and (not is_filled(card.get("context")) or not is_filled(card.get("need"))): return 0
    if key == "context" and str(card.get("context")).strip() == str(card.get("need")).strip(): return 1
    if len(source) < (8 if key == "contact" else 24): return 1
    if key == "contact": return 3 if re.search(r"\S+@\S+\.\S+|@[A-Za-z0-9_]{4,}|\+\d{8,}", source) else 1
    if key == "success_criteria" and not re.search(r"\d", source): return 1
    if key == "interaction_format" and not re.search(r"\d|недел|месяц|ежеднев|weekly|monthly", source, re.I): return 1
    if key == "context": return 3 if len(source) >= 65 else 2
    if key == "data": return 3 if re.search(r"доступ|передаст|выгруз|ссылк|предостав|repo|access|export", source, re.I) else 2
    if key == "expected_result": return 3 if re.search(r"прототип|дашборд|отчёт|отчет|сервис|интерфейс|prototype|dashboard|report", source, re.I) else 2
    if key == "success_criteria": return 3 if re.search(r"минут|час|%|процент|пользоват|сценари|minute|hour|user|scenario", source, re.I) else 2
    if key == "constraints": return 3 if re.search(r"срок|недел|без |доступ|бюджет|week|without|deadline", source, re.I) else 2
    if key == "users": return 3 if re.search(r"\d|курс|факультет|деканат|библиотек|year|faculty|office", source, re.I) else 2
    if key == "interaction_format": return 3 if re.search(r"zoom|meet|teams|telegram|почт|очно|звон|call", source, re.I) else 2
    return 2


def _quality_cap(key: str, source: str, card: dict[str, Any]) -> tuple[int, str]:
    """Hard guards for requirements the model must not wave away."""
    if key == "context" and str(card.get("context", "")).strip() == str(card.get("need", "")).strip():
        return 1, "Текущая ситуация и желаемое изменение повторяют друг друга."
    if key == "data" and not re.search(r"доступ|передаст|выгруз|ссылк|предостав|repo|access|export|download|provide", source, re.I):
        return 2, "Не указан способ доступа команды к данным или материалам."
    if key == "expected_result" and len(source) < 45:
        return 2, "Артефакт назван, но его состав и границы пока не раскрыты."
    if key == "success_criteria" and not re.search(r"\d", source):
        return 2, "Нет измеримого порога успеха."
    if key == "success_criteria" and not re.search(r"тест|замер|опрос|провер|демо|наблюден|test|measure|survey|verify", source, re.I):
        return 3, "Не описан способ проверки показателя."
    if key == "interaction_format" and not re.search(r"\d|недел|месяц|ежеднев|weekly|monthly", source, re.I):
        return 2, "Не указана частота обратной связи."
    if key == "interaction_format" and not re.search(r"zoom|meet|teams|telegram|почт|очно|звон|встреч|call|email", source, re.I):
        return 2, "Не указан канал или тип консультации."
    if key == "users" and not re.search(r"котор|ищут|наход|отвеч|получа|запис|использ|who|need|search|find|answer|book|use", source, re.I):
        return 2, "Группа названа, но не описана её задача в этом сценарии."
    if key == "contact" and not re.search(r"\S+@\S+\.\S+|@[A-Za-z0-9_]{4,}|\+\d{8,}", source):
        return 1, "Не указан проверяемый канал связи."
    return 4, ""


def calculate_rating(card: dict[str, Any]) -> dict[str, Any]:
    """Only confirmed fields score; AI levels require exact evidence in that field."""
    confirmed = set(card.get("confirmed_fields", []))
    review = card.get("quality_review") or {}
    breakdown: list[dict[str, Any]] = []
    missing: list[str] = []
    score = 0

    for key, (label, points) in SCORING_RULES.items():
        source = _source(card, key)
        has_value = is_filled(source) and (key != "context" or (is_filled(card.get("context")) and is_filled(card.get("need"))))
        confirmed_for_score = {"context", "need"}.issubset(confirmed) if key == "context" else key in confirmed
        item = review.get(key, {}) if isinstance(review, dict) else {}
        evidence = str(item.get("evidence") or "").strip()
        ai_valid = bool(evidence and evidence.casefold() in source.casefold())
        local_level = _local_level(key, source, card)
        if ai_valid:
            try: level = max(0, min(4, int(item.get("level", 0))))
            except (TypeError, ValueError): level = 0
            if local_level <= 1: level = min(level, 1)
        else:
            level = local_level
        cap, cap_reason = _quality_cap(key, source, card)
        level = min(level, cap)
        earned = round(points * level / 4) if has_value and confirmed_for_score else 0
        score += earned
        breakdown.append({
            "key": key, "field": label, "max": points, "earned": earned,
            "level": level if has_value else 0, "evidence": evidence if ai_valid else source[:110],
            "reason": cap_reason or (str(item.get("reason") or "").strip() if ai_valid else ("Поле не подтверждено человеком." if not confirmed_for_score else "Локальная предварительная оценка.")),
            "next_step": NEXT_STEPS[key] if cap_reason else (str(item.get("next_step") or "").strip() if ai_valid else NEXT_STEPS[key]),
            "source": "AI + rule" if ai_valid and cap_reason else ("AI" if ai_valid else "local"),
        })
        if not has_value:
            missing.append(label)

    improvements = [f"{item['field']}: {item['next_step']}" for item in breakdown if item["earned"] < item["max"]]
    return {
        "score": score,
        "level": readiness_level(score),
        "breakdown": breakdown,
        "missing": missing,
        "improvements": improvements,
    }
