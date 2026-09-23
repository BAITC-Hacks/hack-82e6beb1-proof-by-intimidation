"""Deterministic tools and JSON schemas exposed to the model."""

from __future__ import annotations

import re
from typing import Any, Callable

from rating import CARD_FIELDS, calculate_rating, is_filled

FIELD_HINTS = {
    "title": ["назван", "проект", "сервис"],
    "context": ["сейчас", "проблем", "контекст", "ситуац"],
    "need": ["нужно", "хотим", "требует", "задач"],
    "users": ["студент", "пользоват", "учител", "команд"],
    "data": ["данн", "csv", "json", "таблиц", "материал"],
    "constraints": ["срок", "огранич", "бюджет", "доступ", "технолог"],
    "expected_result": ["результат", "прототип", "мvp", "готов"],
    "success_criteria": ["успех", "метрик", "измер", "критери"],
    "contact": ["контакт", "почт", "telegram", "связ"],
    "interaction_format": ["встреч", "консультац", "формат", "обратн"],
}

QUESTIONS = {
    "title": "Как коротко назвать задачу?",
    "context": "Что происходит сейчас и почему это стало проблемой?",
    "need": "Что именно нужно изменить или решить?",
    "users": "Для кого создаётся решение и кто будет им пользоваться?",
    "data": "Какие данные, примеры или материалы доступны команде?",
    "constraints": "Какие есть сроки, технологии, доступы или другие ограничения?",
    "expected_result": "Какой конкретный результат должна передать команда?",
    "success_criteria": "По каким измеримым признакам вы примете результат?",
    "contact": "Как с вами связаться для уточнений?",
    "interaction_format": "Какой формат консультаций и обратной связи вам удобен?",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[а-яёa-z0-9]+", text.lower()))


def analyze_draft(draft: str) -> dict[str, Any]:
    words = _words(draft)
    found = []
    missing = []
    for field, hints in FIELD_HINTS.items():
        if any(any(hint in word for word in words) for hint in hints):
            found.append(field)
        else:
            missing.append(field)
    return {"missing_fields": missing, "detected_fields": found, "draft_length": len(draft.strip())}


def propose_questions(missing_fields: list[str], draft: str = "") -> dict[str, Any]:
    selected = [QUESTIONS[field] for field in missing_fields if field in QUESTIONS][:5]
    return {"questions": selected, "for_fields": missing_fields[:5]}


def build_card(draft: str, answers: dict[str, str]) -> dict[str, Any]:
    card = {field: str(answers.get(field, "")).strip() for field in CARD_FIELDS}
    card["draft"] = draft.strip()
    card["title"] = card["title"] or "Новая бизнес-задача"
    card["context"] = card["context"] or draft.strip()
    card["need"] = card["need"] or draft.strip()
    card["confirmed_fields"] = [field for field, value in card.items() if field in CARD_FIELDS and is_filled(value)]
    return {"card": card, "used_answer_fields": [field for field in answers if is_filled(answers[field])]}


def score_card(card: dict[str, Any]) -> dict[str, Any]:
    return calculate_rating(card)


TOOL_SCHEMAS = [
    {"type": "function", "name": "analyze_draft", "description": "Проверяет, каких сведений не хватает в черновике бизнес-задачи.", "parameters": {"type": "object", "properties": {"draft": {"type": "string"}}, "required": ["draft"], "additionalProperties": False}},
    {"type": "function", "name": "propose_questions", "description": "Формирует уместные вопросы по недостающим полям карточки.", "parameters": {"type": "object", "properties": {"missing_fields": {"type": "array", "items": {"type": "string"}}, "draft": {"type": "string"}}, "required": ["missing_fields"], "additionalProperties": False}},
    {"type": "function", "name": "build_card", "description": "Собирает редактируемую карточку только из черновика и ответов пользователя.", "parameters": {"type": "object", "properties": {"draft": {"type": "string"}, "answers": {"type": "object", "additionalProperties": {"type": "string"}}}, "required": ["draft", "answers"], "additionalProperties": False}},
    {"type": "function", "name": "score_card", "description": "Рассчитывает прозрачный рейтинг готовности 0-100.", "parameters": {"type": "object", "properties": {"card": {"type": "object"}}, "required": ["card"], "additionalProperties": False}},
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "analyze_draft": analyze_draft,
    "propose_questions": propose_questions,
    "build_card": build_card,
    "score_card": score_card,
}
