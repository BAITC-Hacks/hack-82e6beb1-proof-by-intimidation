"""A bounded OpenAI Responses agent that turns a draft into a grounded brief.

No automatic offline fallback: a failed real analysis is a visible failure.
The server is responsible for human confirmation, publishing and persistence.
"""

from __future__ import annotations

import json
import os
import re
import time
from uuid import uuid4
from typing import Any

from dotenv import load_dotenv

from agent.architect_prompts import AUDIT_PROMPT, FACET_PROMPT, LANGUAGE_INSTRUCTIONS, OUTPUT_SCHEMA, REPAIR_PROMPT, SYSTEM_PROMPT
from agent.evidence import compact, original_quote, resolve_spans, source_passages
from agent.architect_tools import (
    FACETS, FIELDS, LANG_INDEX, RUBRIC, TOOL_SCHEMAS, compare_revision, get_rubric,
    score_card_fields, source_for, verify_quotes,
)

load_dotenv()


class AnalysisUnavailable(RuntimeError):
    """A safe, user-facing analysis failure; never contains provider credentials."""

    def __init__(self, message: str, *, code: str = "provider_unavailable", stage: str = "agent"):
        super().__init__(message)
        self.code, self.stage, self.diagnostic_id = code, stage, uuid4().hex[:12]


class AnalysisValidationError(ValueError):
    """Model output did not satisfy the grounded briefing contract."""


def _message(language: str, ru: str, kk: str, en: str) -> str:
    return (ru, kk, en)[LANG_INDEX.get(language, 0)]


def _validate_input(draft: str, answers: dict[str, str] | None, language: str) -> tuple[str, dict[str, str]]:
    if language not in LANG_INDEX:
        raise ValueError("Choose a supported language: ru, kk or en.")
    if not isinstance(draft, str) or not 12 <= len(draft.strip()) <= 12000:
        raise ValueError(_message(language, "Опишите задачу: от 12 до 12 000 символов.", "Тапсырманы 12–12 000 таңбамен сипаттаңыз.", "Describe the task using 12–12,000 characters."))
    if len(re.findall(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", draft)) < 5:
        raise ValueError(_message(language, "Добавьте описание задачи словами на русском, казахском или английском.", "Тапсырманы қазақша, орысша немесе ағылшынша сөзбен сипаттаңыз.", "Describe the task in words in English, Kazakh or Russian."))
    if answers is None:
        answers = {}
    if not isinstance(answers, dict) or any(key not in FIELDS or not isinstance(value, str) or len(value) > 4000 for key, value in answers.items()) or sum(len(value) for value in answers.values()) > 24000:
        raise ValueError(_message(language, "Ответы должны соответствовать полям карточки; максимум 4 000 символов на поле.", "Жауаптар карточка өрістеріне сәйкес келуі керек; әр өріске 4 000 таңбаға дейін.", "Answers must match card fields, with at most 4,000 characters per field."))
    if len(answers.get("title", "")) > 180:
        raise ValueError(_message(language, "Название должно быть не длиннее 180 символов.", "Атау 180 таңбадан аспауы керек.", "The title must be at most 180 characters."))
    return draft.strip(), {key: value.strip() for key, value in answers.items()}


def _sources(draft: str, answers: dict[str, str]) -> dict[str, str]:
    return {"draft": draft, **{f"answers.{key}": value for key, value in answers.items()}}


def _source_title(draft: str) -> str:
    first = re.split(r"[.!?\n]", draft, maxsplit=1)[0].strip()
    return first if len(first) <= 90 else first[:90].rsplit(" ", 1)[0] or first[:90]


def _validate_fields(fields: Any, draft: str, answers: dict[str, str]) -> dict[str, str]:
    if not isinstance(fields, dict) or set(fields) != set(FIELDS) or not all(isinstance(value, str) for value in fields.values()):
        raise AnalysisValidationError("fields must contain exactly the ten string fields")
    fields = dict(fields)
    # A title is a label, not a scored fact. If the model paraphrases it, use a
    # safe verbatim label from the owner rather than failing the entire brief.
    if "title" not in answers and (not fields["title"] or fields["title"] not in draft):
        fields["title"] = _source_title(draft)
    sources = _sources(draft, answers)
    for field, value in fields.items():
        if field in answers:
            if compact(value) != compact(answers[field]):
                raise AnalysisValidationError(f"{field}: preserve the corresponding answer verbatim")
            fields[field] = answers[field]
        elif value:
            try:
                spans = resolve_spans(value, sources, protect_negation=field != "title")
            except ValueError as exc:
                raise AnalysisValidationError(f"{field}: {exc}") from exc
            fields[field] = "\n".join(span["quote"] for span in spans)
        if len(fields[field]) > 4000:
            raise AnalysisValidationError(f"{field}: select at most 4000 source characters")
    if sum(map(len, fields.values())) > 24000:
        raise AnalysisValidationError("select relevant passages only; total fields exceed 24000 characters")
    return fields


def _field_evidence(fields: dict[str, str], draft: str, answers: dict[str, str]) -> list[dict[str, str]]:
    evidence = []
    for field, value in fields.items():
        if not value:
            continue
        spans = ([{"source": f"answers.{field}", "quote": value}] if field in answers else
                 resolve_spans(value, _sources(draft, answers), protect_negation=field != "title"))
        evidence.extend({"field": field, **span} for span in spans)
    return evidence


def _coverage_fields(raw: dict[str, Any], draft: str, answers: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    passages = {item["id"]: item for item in source_passages(_sources(draft, answers))}
    coverage = raw.get("coverage")
    if not isinstance(coverage, list) or len(coverage) > 2 * len(passages):
        raise AnalysisValidationError("coverage: classify every source passage exactly once")
    fields = {field: answers.get(field, "") for field in FIELDS}
    evidence, seen = [], set()
    for item in coverage:
        if not isinstance(item, dict) or item.get("source_id") not in passages:
            raise AnalysisValidationError("coverage: unknown source passage ID")
        seen.add(item["source_id"])
        labels = item.get("fields")
        if not isinstance(labels, list) or any(label not in FIELDS for label in labels) or len(set(labels)) != len(labels):
            raise AnalysisValidationError("coverage: use distinct supported field names")
        existing_material = item.get("contains_existing_material", False)
        if not isinstance(existing_material, bool):
            raise AnalysisValidationError("coverage: existing material classification must be boolean")
        if existing_material and "data" not in labels:
            labels = [*labels, "data"]
        passage = passages[item["source_id"]]
        for field in labels:
            if field in answers or field == "title":
                continue
            if passage["quote"] not in fields[field]:
                fields[field] += ("\n" if fields[field] else "") + passage["quote"]
                evidence.append({"field": field, "source": passage["source"], "quote": passage["quote"]})
    if seen != set(passages):
        raise AnalysisValidationError("coverage: classify every source passage; missing IDs " + ",".join(sorted(set(passages)-seen)))
    fields["title"] = answers.get("title", raw.get("title", ""))
    if not isinstance(fields["title"], str):
        raise AnalysisValidationError("title must be a string")
    if "title" not in answers and (not fields["title"] or len(fields["title"]) > 180 or original_quote(fields["title"], draft) is None):
        fields["title"] = _source_title(draft)
    if fields["title"] and "title" not in answers:
        fields["title"] = original_quote(fields["title"], draft) or fields["title"]
        evidence.append({"field": "title", "source": "draft", "quote": fields["title"]})
    evidence.extend({"field": key, "source": f"answers.{key}", "quote": value} for key, value in answers.items() if value)
    if any(len(value) > (180 if key == "title" else 4000) for key, value in fields.items()) or sum(map(len, fields.values())) > 24000:
        raise AnalysisValidationError("coverage: retain relevant passages only; field limit4000, title180, total24000")
    return fields, evidence


def _assess_requirements(raw: dict[str, Any], draft: str, answers: dict[str, str]) -> None:
    """Derive semantic levels from a fixed, source-linked readiness checklist.

    Older saved/mocked reviews remain readable. Live schema requires assessment.
    The model classifies meaning; no domain keyword heuristic invents completeness.
    """
    passages = {item["id"]: item for item in source_passages(_sources(draft, answers))}
    for item in raw.get("criteria", []) if isinstance(raw.get("criteria"), list) else []:
        if not isinstance(item, dict) or "assessment" not in item:
            continue
        key, assessment = item.get("key"), item["assessment"]
        if (key not in FACETS or not isinstance(assessment, list)
            or len(assessment) != len(FACETS[key])
            or any(not isinstance(facet, dict) for facet in assessment)
            or {facet.get("id") for facet in assessment} != set(FACETS[key])):
            raise AnalysisValidationError("assessment: return every fixed requirement for its criterion exactly once")
        for facet in assessment:
            ids, state = facet.get("source_ids"), facet.get("state")
            if (state not in {"met", "partial", "missing", "blocked"}
                or not isinstance(ids, list) or any(source_id not in passages for source_id in ids)
                or (state == "missing" and ids) or (state != "missing" and not ids)):
                raise AnalysisValidationError("assessment: met/partial/blocked requirements need original source IDs; missing needs none")
            if not all(isinstance(facet.get(name), str) and facet[name].strip() and len(facet[name]) <= 700 for name in ("observation", "next_step")):
                raise AnalysisValidationError("assessment: each requirement needs a concise observation and next step")
            # Requirement evidence also repairs omissions in the general field
            # mapping. Original passages and explicit owner answers stay intact.
            if "coverage" in raw:
                field = FACETS[key][facet["id"]][0]
                for entry in raw["coverage"] if isinstance(raw["coverage"], list) else []:
                    if isinstance(entry, dict) and entry.get("source_id") in ids and isinstance(entry.get("fields"), list) and field not in entry["fields"]:
                        entry["fields"].append(field)
        states = [facet["state"] for facet in assessment]
        if "blocked" in states or all(state == "missing" for state in states):
            level = 0
        elif all(state == "met" for state in states):
            level = 4
        elif "met" in states:
            level = 2 if "missing" in states else 3
        else:
            level = 1
        priority = {"blocked": 0, "missing": 1, "partial": 2, "met": 3}
        next_facet = min(assessment, key=lambda facet: priority[facet["state"]])
        item.update(level=level, reason=" ".join(dict.fromkeys(facet["observation"].strip() for facet in assessment)), next_step=next_facet["next_step"].strip())
        # Never retain a stale evidence quote from a model's old holistic score.
        item.pop("evidence", None)


def validate_analysis(raw: Any, draft: str, answers: dict[str, str], language: str = "ru") -> dict[str, Any]:
    """Validate content independently of the provider's JSON schema guarantees."""
    if not isinstance(raw, dict):
        raise AnalysisValidationError("the final answer must be an object")
    task_present = raw.get("task_present", True)
    if not isinstance(task_present, bool):
        raise AnalysisValidationError("task_present must be a boolean")
    _assess_requirements(raw, draft, answers)
    coverage_mode = "coverage" in raw
    fields, coverage_evidence = _coverage_fields(raw, draft, answers) if coverage_mode else (_validate_fields(raw.get("fields"), draft, answers), None)
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 1400:
        raise AnalysisValidationError("summary must be concise and nonempty")
    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
        raise AnalysisValidationError("evidence must be a list")
    checks = verify_quotes(evidence, _sources(draft, answers))
    if not checks["valid"]:
        raise AnalysisValidationError("evidence contains an invented quote or a wrong source/field")
    for item in evidence:
        if original_quote(item["quote"], fields[item["field"]]) is None:
            raise AnalysisValidationError(f"{item['field']}: evidence must support the extracted field")
    # Fields have already passed exact source validation. Build the final source
    # map deterministically, instead of asking the model to duplicate every field
    # perfectly in a second array (a missing duplicate is not an invented fact).
    evidence = coverage_evidence if coverage_mode else _field_evidence(fields, draft, answers)
    questions = raw.get("questions")
    if not isinstance(questions, list) or not 3 <= len(questions) <= 5:
        raise AnalysisValidationError("return 3 to 5 distinct useful questions")
    seen_fields, seen_questions = set(), set()
    for question in questions:
        if not isinstance(question, dict) or question.get("field") not in FIELDS:
            raise AnalysisValidationError("each question must target a valid field")
        field = question["field"]
        text = question.get("question", "")
        if not all(isinstance(question.get(key), str) and question[key].strip() for key in ("question", "why", "answer_hint")) or len(text) > 600:
            raise AnalysisValidationError("questions need a concise question, why and answer_hint")
        normalized = re.sub(r"\W+", "", text.casefold())
        if field in seen_fields or normalized in seen_questions:
            raise AnalysisValidationError("questions must be distinct and target different fields")
        if question.get("priority") not in {"high", "medium"}:
            raise AnalysisValidationError("invalid question priority")
        seen_fields.add(field)
        seen_questions.add(normalized)
        question["id"] = field
    review = raw.get("criteria")
    if not isinstance(review, list) or len(review) != len(RUBRIC) or any(not isinstance(item, dict) for item in review) or {item.get("key") for item in review} != set(RUBRIC):
        raise AnalysisValidationError("return each of the seven rubric criteria exactly once")
    for item in review:
        # Criterion keys have a fixed field mapping. Attach exact validated text
        # as evidence; the model only judges that text's semantic usefulness.
        # This avoids another lossy model transcription of Russian/Kazakh facts.
        # Absence is deterministic, not a semantic model judgment. A spurious
        # positive level for an empty field earns zero instead of breaking the
        # whole otherwise grounded card.
        status = item.get("status", "usable")
        if status not in {"usable", "missing", "unknown", "irrelevant", "contradictory", "unverifiable"}:
            raise AnalysisValidationError("criterion status must describe whether its information is usable")
        if not task_present or status != "usable" or not source_for(fields, item["key"]):
            item["level"] = 0
        if "evidence" not in item:
            item["evidence"] = source_for(fields, item["key"]) if item.get("level", 0) > 0 else ""
        level, quote = item.get("level"), item.get("evidence")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 4:
            raise AnalysisValidationError("criterion level must be an integer 0..4")
        if not isinstance(quote, str) or (quote and quote not in source_for(fields, item["key"])) or (level > 0 and not quote):
            raise AnalysisValidationError(f"{item['key']}: score evidence must be in its corresponding extracted field; empty fields require level zero")
        if not item.get("next_step") and level == 4:
            item["next_step"] = _message(language, "Подтвердите эти сведения перед публикацией.", "Жариялаудан бұрын осы ақпаратты растаңыз.", "Confirm this information before publishing.")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("reason", "next_step")):
            raise AnalysisValidationError("each criterion needs a concrete reason and next step")
    warnings = raw.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise AnalysisValidationError("warnings must be strings")
    contradictions = raw.get("contradictions", [])
    passage_ids = {item["id"] for item in source_passages(_sources(draft, answers))}
    if not isinstance(contradictions, list):
        raise AnalysisValidationError("contradictions must be an array")
    for conflict in contradictions:
        if (not isinstance(conflict, dict) or not isinstance(conflict.get("source_ids"), list) or not conflict["source_ids"]
            or any(source_id not in passage_ids for source_id in conflict["source_ids"])
            or not isinstance(conflict.get("criteria"), list) or not conflict["criteria"] or any(key not in RUBRIC for key in conflict["criteria"])
            or not isinstance(conflict.get("description"), str) or not conflict["description"].strip()):
            raise AnalysisValidationError("contradictions require original source IDs, affected criteria and a description")
        if conflict["description"] not in warnings:
            warnings.append(conflict["description"])
        for item in review:
            if item["key"] in conflict["criteria"]:
                item.update(level=0, evidence=source_for(fields, item["key"]), reason=conflict["description"],
                    next_step=_message(language,
                        "Устраните описанное противоречие: согласуйте совместимые условия до начала работы.",
                        "Жұмыс басталғанға дейін көрсетілген қайшылық бойынша өзара үйлесімді шарттарды келісіңіз.",
                        "Resolve the stated conflict: agree compatible conditions before work begins."))
    prose = [summary] + [item[key] for item in questions for key in ("question", "why", "answer_hint")] + [item[key] for item in review for key in ("reason", "next_step")]
    alphabet = r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]" if language in {"ru", "kk"} else r"[A-Za-z]"
    if any(len(re.findall(alphabet, text)) < 3 for text in prose):
        raise AnalysisValidationError(f"ALL generated UI prose must use language {language}; do not switch to English in questions or summary")
    if language == "kk" and not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", " ".join(prose)):
        raise AnalysisValidationError("use Kazakh, not Russian, for generated UI prose")
    rating = score_card_fields(fields, review, language)
    for item in rating["criteria"]:
        assessed = next(candidate for candidate in review if candidate["key"] == item["key"])
        if "assessment" in assessed:
            item["assessment"] = assessed["assessment"]
            if item["level"] == 4:
                item["next_step"] = _message(language, "Подтвердите эти сведения перед публикацией.", "Жариялаудан бұрын осы ақпаратты растаңыз.", "Confirm this information before publishing.")
    for question in questions:
        criterion = next((item for item in rating["criteria"] if question["field"] in RUBRIC[item["key"]]["fields"]), None)
        question["max_points"] = criterion["weight"] - criterion["points"] if criterion else 0
        if question["max_points"] == 0:
            question["priority"] = "medium"
    return {"summary": summary.strip(), "task_present": task_present, "fields": fields, "questions": questions, "warnings": warnings, "evidence": evidence, **rating}


def _offline(draft: str, answers: dict[str, str], language: str) -> dict[str, Any]:
    fields = {key: answers.get(key, "") for key in FIELDS}
    remaining = 24000 - sum(map(len, fields.values()))
    if "title" not in answers:
        fields["title"] = _source_title(draft)[:max(0, remaining)]
        remaining -= len(fields["title"])
    if "context" not in answers:
        fields["context"] = draft[:max(0, min(4000, remaining))]
    subject = draft[:95].rstrip()
    patterns = {
        "data": (
            f"Для задачи «{subject}» какие материалы команда сможет получить и каким способом?",
            f"«{subject}» тапсырмасы үшін команда қандай материалдарды және қалай ала алады?",
            f"For “{subject}”, what existing materials can the team access, and how?",
        ),
        "success_criteria": (
            f"Как вы проверите, что ситуация «{subject}» улучшилась?",
            f"«{subject}» жағдайының жақсарғанын қалай тексересіз?",
            f"How will you check whether “{subject}” has improved?",
        ),
        "expected_result": (
            f"Какой конкретный результат команда должна передать для задачи «{subject}»?",
            f"«{subject}» тапсырмасы бойынша команда қандай нақты нәтиже тапсыруы керек?",
            f"What specific deliverable should the team hand over for “{subject}”?",
        ),
        "users": (
            f"Кто столкнулся с ситуацией «{subject}» и что ему нужно сделать?",
            f"«{subject}» жағдайына кім тап болды және оған не істеу керек?",
            f"Who experiences “{subject}” and what do they need to accomplish?",
        ),
        "constraints": (
            f"Какие сроки и границы работы важны для задачи «{subject}»?",
            f"«{subject}» тапсырмасы үшін қандай мерзімдер мен шектеулер маңызды?",
            f"What deadlines and scope boundaries apply to “{subject}”?",
        ),
    }
    missing = [field for field in patterns if not fields[field]]
    selected = (missing + [field for field in patterns if field not in missing])[:3]
    rating = score_card_fields(fields, language=language)
    index = LANG_INDEX[language]
    questions = [{
        "id": field, "field": field, "question": patterns[field][index],
        "why": _message(language, "Локальная проверка структуры; смысловую оценку выполнит AI после подключения.", "Бұл жергілікті құрылым тексеруі; мағыналық бағалауды AI қосылғанда жасайды.", "Local structure check; connect AI for a semantic assessment."),
        "answer_hint": _message(language, "Укажите только известные вам факты. Неизвестное можно оставить пустым.", "Тек өзіңіз білетін деректерді жазыңыз. Белгісіз ақпаратты бос қалдырыңыз.", "Use facts you know. Leave unknown information blank."),
        "priority": "high", "max_points": next(item["weight"] - item["points"] for item in rating["criteria"] if field in RUBRIC[item["key"]]["fields"]),
    } for field in selected]
    evidence = [{"field": field, "quote": value, "source": f"answers.{field}" if field in answers else "draft"} for field, value in fields.items() if value]
    warnings = [_message(language, "Офлайн-режим выбран явно. Вопросы локальные, баллы консервативные и предварительные.", "Офлайн режимі таңдалды. Сұрақтар жергілікті, ұпайлар сақтықпен алдын ала есептелген.", "Explicit offline mode. Questions are local; points are conservative previews.")]
    if "context" not in answers and len(draft) > len(fields["context"]):
        warnings.append(_message(language, "Офлайн-карточка содержит только начало черновика из-за ограничения объёма полей. Полный черновик сохранён; отредактируйте карточку перед публикацией.", "Өрістер көлемінің шектеуіне байланысты офлайн карточкаға мәтіннің басы ғана енгізілді. Толық мәтін сақталған; жариялаудан бұрын карточканы өңдеңіз.", "The offline card contains only the beginning of the draft because of field-size limits. Your full draft is preserved; edit the card before publishing."))
    return {
        "mode": "offline", "model": None,
        "summary": _message(language, "Офлайн: сохранены ваши слова. Доступна только предварительная проверка заполнения, без AI-анализа смысла.", "Офлайн: сіздің сөздеріңіз сақталды. AI мағыналық талдауы жоқ, тек толтырылуын алдын ала тексеру қолжетімді.", "Offline: your words are preserved. This is a preliminary presence check, without AI semantic analysis."),
        "fields": fields, "questions": questions, **rating,
        "warnings": warnings,
        "trace": [{"tool": "local_presence_check", "summary": _message(language, "AI не вызывался; проверено наличие полей.", "AI шақырылмады; өрістердің толтырылуы тексерілді.", "No AI call; checked supplied fields."), "elapsed_ms": 0}],
        "evidence": evidence,
    }


def _execute_tool(name: str, arguments: dict[str, Any], draft: str, answers: dict[str, str], language: str) -> dict[str, Any]:
    if name == "get_readiness_rubric":
        return get_rubric(language)
    if name == "verify_user_evidence":
        return verify_quotes(arguments["claims"], _sources(draft, answers), max_claims=40)
    if name == "calculate_readiness":
        fields = _validate_fields(arguments["fields"], draft, answers)
        return score_card_fields(fields, arguments["criteria"], language)
    if name == "compare_revision":
        fields = _validate_fields(arguments["fields"], draft, answers)
        previous = _validate_fields(arguments["previous_fields"], draft, {})
        return compare_revision(fields, previous)
    return {"error": "Unknown tool. Choose an available briefing tool."}


def _trace_summary(name: str, result: dict[str, Any], language: str) -> str:
    if result.get("error"):
        return _message(language, "Аргументы инструмента не прошли проверку; отправлено замечание AI.", "Құрал аргументтері тексеруден өтпеді; ескерту AI-ға жіберілді.", "Tool arguments failed validation; feedback sent to AI.")
    if name == "get_readiness_rubric":
        return _message(language, "Получены 7 критериев и шкала на 100 баллов.", "7 өлшем мен 100 ұпайлық шкала алынды.", "Retrieved seven criteria and the 100-point rubric.")
    if name == "verify_user_evidence":
        checked = len(result["checks"])
        valid = sum(item["valid"] for item in result["checks"])
        return _message(language, f"Подтверждены {valid} из {checked} цитат в вашем тексте.", f"Мәтініңіздегі {checked} дәйексөздің {valid} расталды.", f"Verified {valid} of {checked} quotes against your text.")
    if name == "calculate_readiness":
        return _message(language, f"Рассчитан предварительный рейтинг: {result['score']}/100.", f"Алдын ала рейтинг есептелді: {result['score']}/100.", f"Calculated preview readiness: {result['score']}/100.")
    return _message(language, "Сопоставлены поля карточки и ответы представителя бизнеса.", "Карточка өрістері бизнес өкілінің жауаптарымен салыстырылды.", "Compared extracted card fields with the business owner's answers.")


def _input_preview(arguments: Any) -> dict[str, Any]:
    """Bounded user/tool input audit, never a provider response or hidden prompt."""
    serialized = json.dumps(arguments if isinstance(arguments, dict) else {}, ensure_ascii=False)
    serialized = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[REDACTED]", serialized)
    truncated = len(serialized) > 1200
    return {"input_preview": serialized[:1200] + (" … [truncated]" if truncated else ""), "input_truncated": truncated}


def _run(client: Any, model: str, draft: str, answers: dict[str, str], language: str) -> dict[str, Any]:
    instructions = SYSTEM_PROMPT + "\n" + LANGUAGE_INSTRUCTIONS[language] + "\n" + FACET_PROMPT
    source_data = {"draft": draft, "answers": answers, "source_passages": source_passages(_sources(draft, answers)), "rubric": get_rubric(language), "language": language, "score_is_preview": True}
    conversation: list[Any] = [{"role": "user", "content": json.dumps(source_data, ensure_ascii=False)}]
    trace, calls_used, verified = [], 0, False
    output_text = ""
    started = time.perf_counter()
    for round_number in range(4):
        # "required" asks the model to choose a tool, never a fixed function.
        # Small models otherwise sometimes bypass tools despite the instructions.
        tool_choice = "none" if calls_used >= 6 or round_number == 3 else "required" if calls_used < 2 or not verified else "auto"
        response = client.responses.create(
            model=model, instructions=instructions, input=conversation,
            tools=TOOL_SCHEMAS, tool_choice=tool_choice,
            max_output_tokens=6500, store=False, temperature=0,
            text={"format": {"type": "json_schema", "name": "business_brief", "strict": True, "schema": OUTPUT_SCHEMA}},
        )
        conversation.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            output_text = response.output_text
            if calls_used >= 2 and verified:
                break
            if round_number < 3:
                conversation.append({"role": "user", "content": "Before returning the result, make at least two useful tool calls in total and verify your evidence with verify_user_evidence. Choose appropriate tools yourself."})
                continue
            # A failed preliminary quote is not grounds to discard a valid final
            # card. The final source matcher re-verifies every extracted passage.
            break
        for call in calls:
            tool_started = time.perf_counter()
            arguments = None
            if calls_used >= 6:
                result = {"error": "Tool limit reached; return the grounded final answer."}
            else:
                calls_used += 1
                try:
                    arguments = json.loads(call.arguments)
                    result = _execute_tool(call.name, arguments, draft, answers, language)
                    if call.name == "verify_user_evidence" and result.get("valid"):
                        verified = True
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    result = {"error": "Invalid tool arguments or unsupported source text. Use original passages separated by newlines; retain negative qualifiers.", "code": type(exc).__name__}
            trace.append({"tool": call.name, "summary": _trace_summary(call.name, result, language), "elapsed_ms": round((time.perf_counter() - tool_started) * 1000), **_input_preview(arguments)})
            conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
    # One recovery round can finish missing tool work. It shares the existing
    # six-executed-tool ceiling; the model still chooses which functions to use.
    if calls_used < 2 or not any(item["tool"] == "verify_user_evidence" for item in trace):
        conversation.append({"role": "user", "content": "Complete the missing tool work now: at least two tool calls in total, including verify_user_evidence. Verify original source passages. Choose the necessary tools together."})
        response = client.responses.create(model=model, instructions=instructions, input=conversation,
            tools=TOOL_SCHEMAS, tool_choice="required", max_output_tokens=6500, store=False, temperature=0)
        conversation.extend(response.output)
        for call in [item for item in response.output if item.type == "function_call"]:
            arguments = None
            result = {"error": "Tool budget exhausted."}
            if calls_used < 6:
                calls_used += 1
                try:
                    arguments = json.loads(call.arguments)
                    result = _execute_tool(call.name, arguments, draft, answers, language)
                except (ValueError, TypeError, KeyError, AttributeError):
                    result = {"error": "Use original source passages and valid tool arguments."}
            trace.append({"tool": call.name, "summary": _trace_summary(call.name, result, language), "elapsed_ms": 0, **_input_preview(arguments)})
            conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
        if calls_used < 2 or not any(item["tool"] == "verify_user_evidence" for item in trace):
            raise AnalysisValidationError("tool_protocol: required tool work was not completed within the budget")
    repaired = False
    audit_feedback = ""
    if output_text:
        try:
            validate_analysis(json.loads(output_text), draft, answers, language)
        except (ValueError, TypeError, KeyError) as exc:
            # The mandatory audit is also the single repair when the candidate
            # is invalid. Do not start an unbounded succession of corrections.
            repaired = True
            audit_feedback = "\n" + REPAIR_PROMPT + str(exc)[:700]
    # Fresh audit context prevents a long tool transcript from anchoring the
    # reviewer to an earlier omitted field or incorrect grade.
    audit_input = [{"role": "user", "content": json.dumps({"original": source_data, "rubric": get_rubric(language)}, ensure_ascii=False)}]
    audit_started = time.perf_counter()
    response = client.responses.create(model=model, instructions=instructions + "\n" + AUDIT_PROMPT + "\n" + FACET_PROMPT + audit_feedback, input=audit_input,
        max_output_tokens=6500, store=False, temperature=0,
        text={"format": {"type": "json_schema", "name": "business_brief", "strict": True, "schema": OUTPUT_SCHEMA}})
    try:
        result = validate_analysis(json.loads(response.output_text), draft, answers, language)
    except (ValueError, TypeError, KeyError) as exc:
        if repaired:
            raise AnalysisValidationError("repair_failed: " + str(exc)) from exc
        repaired = True
        audit_input.extend(response.output)
        audit_input.append({"role": "user", "content": REPAIR_PROMPT + str(exc)[:700]})
        response = client.responses.create(model=model, instructions=instructions + "\n" + AUDIT_PROMPT + "\n" + FACET_PROMPT, input=audit_input,
            max_output_tokens=6500, store=False, temperature=0,
            text={"format": {"type": "json_schema", "name": "business_brief", "strict": True, "schema": OUTPUT_SCHEMA}})
        result = validate_analysis(json.loads(response.output_text), draft, answers, language)
    if repaired:
        trace.append({"tool": "repair_validation", "summary": _message(language, "AI исправил структуру или цитаты; факты повторно сверены с источником.", "AI құрылымды немесе дәйексөздерді түзетті; деректер дереккөзбен қайта тексерілді.", "AI repaired structure or quotations; facts were rechecked against sources."), "elapsed_ms": 0})
    trace.append({"tool": "semantic_audit", "summary": _message(language, "Проверены пропущенные сведения, отрицания, противоречия и уместность вопросов. Это AI-оценка, не гарантия полноты.", "Түсіп қалған ақпарат, терістеулер, қайшылықтар және сұрақтардың орындылығы тексерілді. Бұл AI бағасы, толықтық кепілдігі емес.", "Checked omitted facts, negations, contradictions and question relevance. This is an AI assessment, not a completeness guarantee."), "elapsed_ms": round((time.perf_counter()-audit_started)*1000), "input_preview": "{}", "input_truncated": False})
    trace.append({"tool": "final_grounding_check", "summary": _message(language, "Все извлечённые факты сверены с вашими словами; рейтинг предварительный.", "Барлық алынған деректер сіздің сөздеріңізбен тексерілді; рейтинг алдын ала.", "All extracted facts checked against your words; rating is a preview."), "elapsed_ms": round((time.perf_counter() - started) * 1000)})
    return {"mode": "ai", "model": model, **result, "trace": trace}


def analyze_brief(draft: str, answers: dict[str, str] | None = None, language: str = "ru", offline: bool = False) -> dict[str, Any]:
    """Run the real agent, or an explicitly requested conservative offline check."""
    draft, answers = _validate_input(draft, answers, language)
    if offline:
        return _offline(draft, answers, language)
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
        raise AnalysisUnavailable(_message(language, "AI пока не подключён. Настройте OPENAI_API_KEY и OPENAI_MODEL на сервере или явно выберите офлайн-проверку.", "AI әлі қосылмаған. Серверде OPENAI_API_KEY және OPENAI_MODEL орнатыңыз немесе офлайн тексеруді таңдаңыз.", "AI is not connected. Configure OPENAI_API_KEY and OPENAI_MODEL on the server, or explicitly choose the offline check."), code="not_configured")
    try:
        from openai import OpenAI

        with OpenAI(timeout=60.0, max_retries=0) as client:
            return _run(client, os.environ["OPENAI_MODEL"], draft, answers, language)
    except (AnalysisValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise AnalysisUnavailable(_message(language, "AI вернул ответ, который не прошёл проверку фактов или структуры. Ваш текст сохранён: повторите анализ или выберите офлайн-проверку.", "AI жауабы деректер немесе құрылым тексеруінен өтпеді. Мәтініңіз сақталды: талдауды қайталаңыз немесе офлайн тексеруді таңдаңыз.", "AI returned an answer that failed fact validation or structure checks. Your text is preserved; retry or choose the offline check."), code="validation_failed", stage="repair" if str(exc).startswith("repair_failed") else "audit") from exc
    except Exception as exc:
        raise AnalysisUnavailable(_message(language, "AI-сервис сейчас недоступен. Ваш текст сохранён. Повторите позже или явно выберите офлайн-проверку.", "AI қызметі қазір қолжетімсіз. Мәтініңіз сақталды. Кейін қайталаңыз немесе офлайн тексеруді таңдаңыз.", "The AI service is currently unavailable. Your text is preserved. Retry later or explicitly choose the offline check.")) from exc
