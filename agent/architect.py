"""A bounded OpenAI Responses agent that turns a draft into a grounded brief.

No automatic offline fallback: a failed real analysis is a visible failure.
The server is responsible for human confirmation, publishing and persistence.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from dotenv import load_dotenv

from agent.architect_prompts import LANGUAGE_INSTRUCTIONS, OUTPUT_SCHEMA, REPAIR_PROMPT, SYSTEM_PROMPT
from agent.architect_tools import (
    FIELDS, LANG_INDEX, RUBRIC, TOOL_SCHEMAS, compare_revision, get_rubric,
    score_card_fields, source_for, verify_quotes,
)

load_dotenv()


class AnalysisUnavailable(RuntimeError):
    """A safe, user-facing analysis failure; never contains provider credentials."""


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
    for field, value in fields.items():
        if field in answers:
            if value != answers[field]:
                raise AnalysisValidationError(f"{field}: preserve the corresponding answer verbatim")
        elif value and value not in draft:
            raise AnalysisValidationError(f"{field}: invented or paraphrased text, not an exact source excerpt")
    return fields


def validate_analysis(raw: Any, draft: str, answers: dict[str, str], language: str = "ru") -> dict[str, Any]:
    """Validate content independently of the provider's JSON schema guarantees."""
    if not isinstance(raw, dict):
        raise AnalysisValidationError("the final answer must be an object")
    fields = _validate_fields(raw.get("fields"), draft, answers)
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
        if item["quote"] not in fields[item["field"]]:
            raise AnalysisValidationError(f"{item['field']}: evidence must support the extracted field")
    # Fields have already passed exact source validation. Build the final source
    # map deterministically, instead of asking the model to duplicate every field
    # perfectly in a second array (a missing duplicate is not an invented fact).
    evidence = [{"field": field, "quote": value, "source": f"answers.{field}" if field in answers else "draft"} for field, value in fields.items() if value]
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
        if "evidence" not in item:
            item["evidence"] = source_for(fields, item["key"]) if item.get("level", 0) > 0 else ""
        level, quote = item.get("level"), item.get("evidence")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 4:
            raise AnalysisValidationError("criterion level must be an integer 0..4")
        if not isinstance(quote, str) or (quote and quote not in source_for(fields, item["key"])) or (level > 0 and not quote):
            raise AnalysisValidationError(f"{item['key']}: score evidence must be in its corresponding extracted field. Use an exact excerpt of {source_for(fields, item['key'])!r}; proposed evidence was {quote!r}")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in ("reason", "next_step")):
            raise AnalysisValidationError("each criterion needs a concrete reason and next step")
    warnings = raw.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise AnalysisValidationError("warnings must be strings")
    prose = [summary] + [item[key] for item in questions for key in ("question", "why", "answer_hint")] + [item[key] for item in review for key in ("reason", "next_step")]
    alphabet = r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]" if language in {"ru", "kk"} else r"[A-Za-z]"
    if any(len(re.findall(alphabet, text)) < 3 for text in prose):
        raise AnalysisValidationError(f"ALL generated UI prose must use language {language}; do not switch to English in questions or summary")
    if language == "kk" and not re.search(r"[ӘәҒғҚқҢңӨөҰұҮүҺһІі]", " ".join(prose)):
        raise AnalysisValidationError("use Kazakh, not Russian, for generated UI prose")
    rating = score_card_fields(fields, review, language)
    for question in questions:
        criterion = next((item for item in rating["criteria"] if question["field"] in RUBRIC[item["key"]]["fields"]), None)
        question["max_points"] = criterion["weight"] - criterion["points"] if criterion else 0
    return {"summary": summary.strip(), "fields": fields, "questions": questions, "warnings": warnings, "evidence": evidence, **rating}


def _offline(draft: str, answers: dict[str, str], language: str) -> dict[str, Any]:
    fields = {key: answers.get(key, "") for key in FIELDS}
    fields["context"] = answers["context"] if "context" in answers else draft
    fields["title"] = answers["title"] if "title" in answers else _source_title(draft)
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
    return {
        "mode": "offline", "model": None,
        "summary": _message(language, "Офлайн: сохранены ваши слова. Доступна только предварительная проверка заполнения, без AI-анализа смысла.", "Офлайн: сіздің сөздеріңіз сақталды. AI мағыналық талдауы жоқ, тек толтырылуын алдын ала тексеру қолжетімді.", "Offline: your words are preserved. This is a preliminary presence check, without AI semantic analysis."),
        "fields": fields, "questions": questions, **rating,
        "warnings": [_message(language, "Офлайн-режим выбран явно. Вопросы локальные, баллы консервативные и предварительные.", "Офлайн режимі таңдалды. Сұрақтар жергілікті, ұпайлар сақтықпен алдын ала есептелген.", "Explicit offline mode. Questions are local; points are conservative previews.")],
        "trace": [{"tool": "local_presence_check", "summary": _message(language, "AI не вызывался; проверено наличие полей.", "AI шақырылмады; өрістердің толтырылуы тексерілді.", "No AI call; checked supplied fields."), "elapsed_ms": 0}],
        "evidence": evidence,
    }


def _execute_tool(name: str, arguments: dict[str, Any], draft: str, answers: dict[str, str], language: str) -> dict[str, Any]:
    if name == "get_readiness_rubric":
        return get_rubric(language)
    if name == "verify_user_evidence":
        return verify_quotes(arguments["claims"], _sources(draft, answers))
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
    instructions = SYSTEM_PROMPT + "\n" + LANGUAGE_INSTRUCTIONS[language]
    conversation: list[Any] = [{"role": "user", "content": json.dumps({"draft": draft, "answers": answers, "language": language, "score_is_preview": True}, ensure_ascii=False)}]
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
            max_output_tokens=6500, store=False,
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
            used = ", ".join(item["tool"] + ": " + item["summary"] for item in trace)
            raise AnalysisValidationError("the agent did not complete evidence checks; " + used)
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
                except (ValueError, TypeError, KeyError, AttributeError):
                    result = {"error": "Invalid tool arguments or unsupported source text. Preserve the supplied fields verbatim and correct the evidence."}
            trace.append({"tool": call.name, "summary": _trace_summary(call.name, result, language), "elapsed_ms": round((time.perf_counter() - tool_started) * 1000), **_input_preview(arguments)})
            conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
    try:
        result = validate_analysis(json.loads(output_text), draft, answers, language)
    except (ValueError, TypeError, KeyError) as exc:
        # One bounded repair; never silently replace invalid AI output with templates.
        conversation.append({"role": "user", "content": REPAIR_PROMPT + str(exc)[:700]})
        response = client.responses.create(
            model=model, instructions=instructions, input=conversation,
            max_output_tokens=6500, store=False,
            text={"format": {"type": "json_schema", "name": "business_brief", "strict": True, "schema": OUTPUT_SCHEMA}},
        )
        result = validate_analysis(json.loads(response.output_text), draft, answers, language)
        trace.append({"tool": "repair_validation", "summary": _message(language, "AI исправил ответ после проверки источников и структуры.", "AI дереккөздер мен құрылым тексерілгеннен кейін жауапты түзетті.", "AI repaired its answer after source and structure validation."), "elapsed_ms": 0})
    trace.append({"tool": "final_grounding_check", "summary": _message(language, "Все извлечённые факты сверены с вашими словами; рейтинг предварительный.", "Барлық алынған деректер сіздің сөздеріңізбен тексерілді; рейтинг алдын ала.", "All extracted facts checked against your words; rating is a preview."), "elapsed_ms": round((time.perf_counter() - started) * 1000)})
    return {"mode": "ai", "model": model, **result, "trace": trace}


def analyze_brief(draft: str, answers: dict[str, str] | None = None, language: str = "ru", offline: bool = False) -> dict[str, Any]:
    """Run the real agent, or an explicitly requested conservative offline check."""
    draft, answers = _validate_input(draft, answers, language)
    if offline:
        return _offline(draft, answers, language)
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("OPENAI_MODEL"):
        raise AnalysisUnavailable(_message(language, "AI пока не подключён. Настройте OPENAI_API_KEY и OPENAI_MODEL на сервере или явно выберите офлайн-проверку.", "AI әлі қосылмаған. Серверде OPENAI_API_KEY және OPENAI_MODEL орнатыңыз немесе офлайн тексеруді таңдаңыз.", "AI is not connected. Configure OPENAI_API_KEY and OPENAI_MODEL on the server, or explicitly choose the offline check."))
    try:
        from openai import OpenAI

        with OpenAI(timeout=60.0, max_retries=0) as client:
            return _run(client, os.environ["OPENAI_MODEL"], draft, answers, language)
    except (AnalysisValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise AnalysisUnavailable(_message(language, "AI вернул ответ, который не прошёл проверку фактов. Ваш текст сохранён: повторите анализ или выберите офлайн-проверку.", "AI жауабы деректерді тексеруден өтпеді. Мәтініңіз сақталды: талдауды қайталаңыз немесе офлайн тексеруді таңдаңыз.", "AI returned an answer that failed fact validation. Your text is preserved; retry the analysis or choose the offline check.")) from exc
    except Exception as exc:
        raise AnalysisUnavailable(_message(language, "AI-сервис сейчас недоступен. Ваш текст сохранён. Повторите позже или явно выберите офлайн-проверку.", "AI қызметі қазір қолжетімсіз. Мәтініңіз сақталды. Кейін қайталаңыз немесе офлайн тексеруді таңдаңыз.", "The AI service is currently unavailable. Your text is preserved. Retry later or explicitly choose the offline check.")) from exc
