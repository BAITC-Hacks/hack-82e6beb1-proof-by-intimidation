"""Small, visible OpenAI tool-calling loop with a labelled offline fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from agent.prompts import QUESTION_RETRY_PROMPT, SYSTEM_PROMPT
from agent.review import review_quality
from agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, analyze_draft, build_card, fallback_questions, propose_questions, score_card

load_dotenv()


def _offline_result(draft: str, answers: dict[str, str]) -> dict[str, Any]:
    analysis = analyze_draft(draft)
    questions = fallback_questions(analysis["missing_fields"])
    card_data = build_card(draft, answers)
    rating = score_card(card_data["card"])
    return {
        "mode": "offline",
        "message": "Офлайн-режим: API недоступен. Вопросы и рейтинг сформированы локально; это не ответ AI.",
        "questions": questions,
        "summary": "Локальная проверка нашла поля, которые стоит уточнить перед публикацией.",
        "highlights": [draft.strip()[:180]] if draft.strip() else [],
        "card": card_data["card"],
        "rating": rating,
        "draft_review": {},
        "steps": [
            {"tool": "analyze_draft", "result": analysis},
            {"tool": "propose_questions", "result": {"fallback": True, "fields": analysis["missing_fields"][:5]}},
            {"tool": "build_card", "result": {"used_answer_fields": card_data["used_answer_fields"]}},
            {"tool": "score_card", "result": rating},
        ],
    }


def _structured_text(text: str) -> dict[str, Any]:
    """Extract the model's final JSON without trusting malformed output."""
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    candidates = [clean]
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            continue
    return {}


def _personalized_questions(client: Any, model: str, draft: str, missing_fields: list[str]) -> list[str]:
    retry = client.responses.create(
        model=model,
        instructions=QUESTION_RETRY_PROMPT,
        input=json.dumps({"draft": draft, "missing_fields": missing_fields}, ensure_ascii=False),
        text={"format": {"type": "json_schema", "name": "grounded_questions", "strict": True, "schema": {"type": "object", "properties": {"questions": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "quote": {"type": "string"}, "question": {"type": "string"}}, "required": ["field", "quote", "question"], "additionalProperties": False}}}, "required": ["questions"], "additionalProperties": False}}},
    )
    items = _structured_text(retry.output_text).get("questions", [])
    result, used_fields = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict): continue
        field = str(item.get("field") or "")
        quote = str(item.get("quote") or "").strip()
        question = str(item.get("question") or "").strip()
        if field in used_fields or field not in {"context", "data", "expected_result", "success_criteria", "constraints", "users", "contact", "interaction_format"}: continue
        if len(quote.split()) < 2 or quote.casefold() not in draft.casefold() or quote.casefold() not in question.casefold(): continue
        if not question.endswith("?") or len(question) > 220: continue
        if not re.search(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", draft) and re.search(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", question): continue
        result.append(question)
        used_fields.add(field)
    return result[:5]


def _grounded_by_draft(questions: list[str], draft: str) -> bool:
    meaningful_words = [word.lower() for word in re.findall(r"[А-Яа-яЁёA-Za-z]{5,}", draft)]
    return bool(questions) and all(any(word in question.lower() for word in meaningful_words) for question in questions)


def _grounded_questions(questions: list[str], draft: str) -> list[str]:
    return [question for question in questions if _grounded_by_draft([question], draft)]


def _contextual_fallback(draft: str, missing_fields: list[str]) -> list[str]:
    """A transparent, non-AI fallback that is tied to this exact draft rather than a generic form."""
    subject = re.sub(r"\s+", " ", re.split(r"[,.!?;]", draft.strip())[0])
    subject = re.sub(r"^(Хотим|Нужно|Ищем способ|Требуется|We want|We need)\s+", "", subject, flags=re.I)[:55].rstrip()
    patterns = {
        "title": f"Как коротко назвать challenge о «{subject}»?",
        "context": f"На каком шаге ситуации «{subject}» возникает основное затруднение?",
        "need": f"Что именно должно измениться в ситуации «{subject}» после работы команды?",
        "users": f"Кто конкретно сталкивается с ситуацией «{subject}» и кто будет использовать решение?",
        "data": f"Где сейчас хранятся сведения по «{subject}» и можно ли передать команде обезличенный пример?",
        "constraints": f"Какие сроки, доступы или правила ограничивают работу над «{subject}»?",
        "expected_result": f"Какой конкретный артефакт команда передаст для «{subject}»?",
        "success_criteria": f"Как измерить улучшение для «{subject}» и какой порог считать успехом?",
        "contact": f"Кто сможет уточнить детали challenge «{subject}»?",
        "interaction_format": f"Как команда сможет получать обратную связь по «{subject}»?",
    }
    priority = ["data", "success_criteria", "expected_result", "constraints", "users", "contact", "interaction_format", "context", "need", "title"]
    return [patterns[field] for field in priority if field in missing_fields][:5]


def run_task_agent(draft: str, answers: dict[str, str] | None = None) -> dict[str, Any]:
    """Run at most six model-selected tool calls; fall back explicitly on failure."""
    answers = answers or {}
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
        return _offline_result(draft, answers)
    try:
        from openai import OpenAI

        client = OpenAI()
        model = os.environ["OPENAI_MODEL"]
        user_input = json.dumps({"draft": draft, "answers": answers, "stage": "card" if answers else "questions"}, ensure_ascii=False)
        response = client.responses.create(model=model, instructions=SYSTEM_PROMPT, input=user_input, tools=TOOL_SCHEMAS)
        steps: list[dict[str, Any]] = []
        captured: dict[str, Any] = {}
        tool_calls_used = 0
        for _ in range(6):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls or tool_calls_used >= 6:
                break
            calls = calls[: 6 - tool_calls_used]
            outputs = []
            for call in calls:
                arguments = json.loads(call.arguments)
                result = TOOL_FUNCTIONS[call.name](**arguments)
                tool_calls_used += 1
                steps.append({"tool": call.name, "result": result})
                if call.name == "build_card":
                    captured["card"] = result["card"]
                if call.name == "score_card":
                    captured["rating"] = result
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
            response = client.responses.create(model=model, instructions=SYSTEM_PROMPT, previous_response_id=response.id, input=outputs, tools=TOOL_SCHEMAS)
        fallback = _offline_result(draft, answers)
        final = _structured_text(response.output_text)
        model_questions = final.get("questions", [])
        if not isinstance(model_questions, list) or len(model_questions) < 3 or not all(isinstance(question, str) and question.strip() for question in model_questions):
            model_questions = fallback["questions"]
        missing_fields = analyze_draft(draft)["missing_fields"]
        question_source = "AI-generated"
        try:
            personalized = _personalized_questions(client, model, draft, missing_fields) if not answers else []
        except Exception:
            personalized = []
        grounded = _grounded_questions(personalized, draft)
        if len(grounded) >= 3:
            model_questions = grounded[:5]
        elif not answers:
            covered = set()
            for question in grounded:
                if re.search(r"данн|баз|хран|источник|доступ|catalog|data|source|access|export", question, re.I): covered.add("data")
                if re.search(r"измер|метрик|порог|успех|measure|metric|success", question, re.I): covered.add("success_criteria")
                if re.search(r"прототип|артефакт|результат|deliver|prototype", question, re.I): covered.add("expected_result")
                if re.search(r"срок|огранич|бюджет|deadline|constraint|budget", question, re.I): covered.add("constraints")
            local = _contextual_fallback(draft, [field for field in missing_fields if field not in covered])
            model_questions = (grounded + [question for question in local if question not in grounded])[:3]
            question_source = "AI + grounded local fallback" if grounded else "Grounded local fallback"
        highlights = final.get("highlights", [])
        if not isinstance(highlights, list):
            highlights = fallback["highlights"]
        highlights = [item.strip() for item in highlights if isinstance(item, str) and item.strip() and item.strip().casefold() in draft.casefold()]
        if not highlights:
            highlights = [draft.strip()[:180]]
        card = build_card(draft, answers)["card"]
        quality_review = {}
        review_status = "AI-оценка недоступна; использована локальная консервативная шкала."
        try:
            quality_review = review_quality(client, model, {key: str(value) for key, value in (card if answers else {"draft": draft}).items()}, draft=not bool(answers))
            review_status = "AI-оценка с проверкой дословных цитат."
        except Exception:  # A review failure must not discard a valid tool loop or user-entered card.
            pass
        if answers:
            card["quality_review"] = quality_review
        return {
            "mode": "ai",
            "message": response.output_text,
            "summary": f"Из вашего описания: «{draft.strip()[:160]}{'…' if len(draft.strip()) > 160 else ''}»",
            "highlights": [str(item) for item in highlights[:3]],
            "questions": model_questions[:5],
            "question_source": question_source,
            "card": card,
            "rating": score_card(card),
            "draft_review": quality_review if not answers else {},
            "review_status": review_status,
            "steps": steps,
        }
    except Exception as exc:  # UI must never expose a stack trace for API failures.
        result = _offline_result(draft, answers)
        result["message"] = f"Офлайн-режим: AI API недоступен ({type(exc).__name__}). {result['message']}"
        return result
