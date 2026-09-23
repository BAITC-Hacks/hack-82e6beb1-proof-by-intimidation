"""Run local contract checks or opt in to real, credit-using AI evaluation.

Examples (from repo root):
  python scripts/evaluate_architect.py
  python scripts/evaluate_architect.py --live --case library_ru --with-answers
  python scripts/evaluate_architect.py --live --limit 12

No API key or provider error payload is printed. Automated checks are regression
signals, not a claim that semantic usefulness has been fully evaluated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.architect import AnalysisUnavailable, AnalysisValidationError, analyze_brief
from agent.architect_tools import verify_quotes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use the configured real API (uses credit). Default is explicitly offline.")
    parser.add_argument("--case", action="append", help="Run one case ID; repeat this option for a selected set.")
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of examples (1–12).")
    parser.add_argument("--with-answers", action="store_true", help="Include supplied clarification answers where available.")
    parser.add_argument("--debug-validation", action="store_true", help="Show local validation failure reasons, never provider payloads or credentials.")
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[1] / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))
    cases = [case for case in cases if not args.case or case["id"] in args.case][:max(1, min(args.limit, 12))]
    if not cases:
        parser.error("Unknown case ID.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    failed = 0
    for case in cases:
        started = time.perf_counter()
        answers = case.get("answers", {}) if args.with_answers else {}
        try:
            result = analyze_brief(case["draft"], answers, case["language"], offline=not args.live)
            sources = {"draft": case["draft"], **{f"answers.{field}": value for field, value in answers.items()}}
            questions = " ".join(question["question"] for question in result["questions"]).casefold()
            serialized_fields = json.dumps(result["fields"], ensure_ascii=False).casefold()
            lower, upper = case.get("answered_score_range", case["score_range"]) if answers else case["score_range"]
            checks = {
                "source_quotes_valid": verify_quotes(result["evidence"], sources)["valid"],
                "at_least_three_distinct_questions": len({question["field"] for question in result["questions"]}) >= 3,
                "no_known_invented_facts": not any(text.casefold() in serialized_fields for text in case["must_not_invent"]),
            }
            if args.live:
                checks.update({"real_ai_mode": result["mode"] == "ai", "score_in_expected_range": lower <= result["score"] <= upper, "questions_reference_case": any(term.casefold() in questions for term in case["question_terms"])})
                checks["explicit_facts_preserved_in_relevant_fields"] = all(all(fragment.casefold() in result["fields"].get(field, "").casefold() for fragment in fragments) for field, fragments in case.get("fields_must_contain", {}).items())
            failed += not all(checks.values())
            print(json.dumps({
                "case": case["id"], "mode": result["mode"], "model": result["model"], "score": result["score"],
                "elapsed_seconds": round(time.perf_counter() - started, 2), "automated_checks": checks,
                "summary": result["summary"], "questions": result["questions"], "criteria": result["criteria"], "warnings": result["warnings"],
                "tools": [item["tool"] for item in result["trace"]], "human_review_required": case["should_notice"],
            }, ensure_ascii=False))
        except (AnalysisUnavailable, ValueError) as exc:
            failed += 1
            debug = {"validation_error": str(exc.__cause__)} if args.debug_validation and isinstance(exc.__cause__, AnalysisValidationError) else {}
            print(json.dumps({"case": case["id"], "mode": "unavailable", "error": str(exc), **debug, "elapsed_seconds": round(time.perf_counter() - started, 2)}, ensure_ascii=False))
    print(json.dumps({"cases": len(cases), "failed_automated_checks": failed, "real_api": args.live, "note": "Review question relevance, grounding and rubric judgments manually; passing contract checks is not a semantic quality guarantee."}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
