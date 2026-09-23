"""Small, visible OpenAI tool-calling loop with a labelled offline fallback."""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, analyze_draft, build_card, propose_questions, score_card

load_dotenv()


def _offline_result(draft: str, answers: dict[str, str]) -> dict[str, Any]:
    analysis = analyze_draft(draft)
    questions = propose_questions(analysis["missing_fields"], draft)
    card_data = build_card(draft, answers)
    rating = score_card(card_data["card"])
    return {
        "mode": "offline",
        "message": "Офлайн-режим: API недоступен. Вопросы и рейтинг сформированы локально; это не ответ AI.",
        "questions": questions["questions"],
        "card": card_data["card"],
        "rating": rating,
        "steps": [
            {"tool": "analyze_draft", "result": analysis},
            {"tool": "propose_questions", "result": questions},
            {"tool": "build_card", "result": {"used_answer_fields": card_data["used_answer_fields"]}},
            {"tool": "score_card", "result": rating},
        ],
    }


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
        for _ in range(6):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                break
            outputs = []
            for call in calls:
                arguments = json.loads(call.arguments)
                result = TOOL_FUNCTIONS[call.name](**arguments)
                steps.append({"tool": call.name, "result": result})
                if call.name == "propose_questions":
                    captured["questions"] = result["questions"]
                if call.name == "build_card":
                    captured["card"] = result["card"]
                if call.name == "score_card":
                    captured["rating"] = result
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, ensure_ascii=False)})
            response = client.responses.create(model=model, instructions=SYSTEM_PROMPT, previous_response_id=response.id, input=outputs, tools=TOOL_SCHEMAS)
        fallback = _offline_result(draft, answers)
        return {"mode": "ai", "message": response.output_text, "questions": captured.get("questions", fallback["questions"]), "card": captured.get("card", fallback["card"]), "rating": captured.get("rating", fallback["rating"]), "steps": steps}
    except Exception as exc:  # UI must never expose a stack trace for API failures.
        result = _offline_result(draft, answers)
        result["message"] = f"Офлайн-режим: AI API недоступен ({type(exc).__name__}). {result['message']}"
        return result
