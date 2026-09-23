"""Six narrow semantic regressions/held-out examples; synthetic sources only.

Default offline runs ONLY contract checks, never claims semantic quality.
--live explicitly authorizes one paid analysis per selected case (at most six).
Reports stay in .qa/, contain public structured results, and omit SDK payloads.
Design: https://developers.openai.com/api/docs/guides/evaluation-best-practices
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_FILES = ("agent/architect.py", "agent/architect_tools.py", "agent/architect_prompts.py",
                "agent/evidence.py", "data/semantic_cases.json", "scripts/evaluate_semantics.py")


def source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def load_cases() -> list[dict[str, Any]]:
    return json.loads((ROOT / "data/semantic_cases.json").read_text(encoding="utf-8"))


def check_result(case: dict[str, Any], result: dict[str, Any], *, live: bool) -> dict[str, Any]:
    from agent.architect_tools import FIELDS, RUBRIC, verify_quotes
    fields, criteria = result.get("fields", {}), result.get("criteria", [])
    sources = {"draft": case["draft"], **{f"answers.{key}": value for key, value in case["answers"].items()}}
    review = {item.get("key"): item for item in criteria if isinstance(item, dict)}
    evidence = result.get("evidence", [])
    score = result.get("score")
    arithmetic = len(criteria) == 7 and set(review) == set(RUBRIC)
    if arithmetic:
        arithmetic = all(isinstance(item.get("level"), int) and not isinstance(item["level"], bool)
                         and 0 <= item["level"] <= 4 and item.get("weight") == RUBRIC[key]["weight"]
                         and item.get("points") == (item["weight"] * item["level"] + 2) // 4
                         for key, item in review.items())
        arithmetic = arithmetic and isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100 and score == sum(item["points"] for item in criteria)
    contract = {
        "honest_mode": result.get("mode") == ("ai" if live else "offline"),
        "ten_string_fields": set(fields) == set(FIELDS) and all(isinstance(value, str) for value in fields.values()),
        "source_evidence_valid": verify_quotes(evidence, sources)["valid"],
        "score_arithmetic": bool(arithmetic),
        "three_distinct_questions": len({item.get("field") for item in result.get("questions", []) if isinstance(item, dict)}) >= 3,
        "explicit_answers_preserved": all(fields.get(key) == value for key, value in case["answers"].items()),
    }
    semantic: dict[str, bool] = {}
    if live:
        for field, facts in case.get("required_field_facts", {}).items():
            semantic[f"facts:{field}"] = all(fact.casefold() in fields.get(field, "").casefold() for fact in facts)
        for key, rule in case.get("criterion_rules", {}).items():
            item = review.get(key, {})
            if rule.get("zero"):
                semantic[f"zero:{key}"] = item.get("level") == 0 and item.get("points") == 0
            if "min_level" in rule:
                semantic[f"minimum:{key}"] = isinstance(item.get("level"), int) and item["level"] >= rule["min_level"]
        for field in case.get("must_be_empty", []):
            semantic[f"empty:{field}"] = fields.get(field) == ""
        if case.get("all_criteria_zero"):
            semantic["all_criteria_zero"] = bool(criteria) and all(item.get("level") == 0 and item.get("points") == 0 for item in criteria) and score == 0
        if case.get("requires_warning"):
            semantic["conflict_warning_present"] = bool(result.get("warnings"))
    return {"contract_checks": contract, "semantic_checks": semantic,
            "semantic_checks_executed": live,
            "manual_review": [{"question": question, "status": "not_reviewed"} for question in case["manual_review"]]}


def safe_error(error: Exception) -> dict[str, str]:
    # No exception text/cause/stack/provider body is copied into reports or stdout.
    code = getattr(error, "code", "evaluation_failed")
    if code not in {"not_configured", "provider_unavailable", "validation_failed"}:
        code = "evaluation_failed"
    result = {"code": code, "detail": "Analysis failed; inspect the safe diagnostic ID and retry explicitly."}
    diagnostic = getattr(error, "diagnostic_id", "")
    if isinstance(diagnostic, str) and re.fullmatch(r"[a-f0-9]{12,64}", diagnostic):
        result["diagnostic_id"] = diagnostic
    return result


def evaluate(cases: list[dict[str, Any]], *, live: bool = False, analyzer: Any = None) -> dict[str, Any]:
    before = source_hashes()
    if analyzer is None:
        from agent.architect import analyze_brief
        analyzer = analyze_brief
    records = []
    for case in cases:
        started = time.perf_counter()
        record = {"case": case["id"], "split": case["split"], "failure_class": case["failure_class"]}
        try:
            result = analyzer(case["draft"], case["answers"], case["language"], offline=not live)
            record.update(check_result(case, result, live=live))
            # Deliberate allowlist: no trace/tool arguments/SDK response are persisted.
            record["result"] = {key: result.get(key) for key in (
                "mode", "model", "score", "readiness", "summary", "fields", "questions", "criteria", "warnings", "evidence",
            )}
            record["passed_automated_checks"] = all(record["contract_checks"].values()) and all(record["semantic_checks"].values())
        except Exception as error:
            record.update(error=safe_error(error), passed_automated_checks=False,
                          semantic_checks_executed=False, manual_review=[{"question": question, "status": "not_reviewed"} for question in case["manual_review"]])
        record["seconds"] = round(time.perf_counter() - started, 3)
        records.append(record)
    after = source_hashes()
    return {"created_at": datetime.now(timezone.utc).isoformat(), "live_ai": live, "cases": len(records),
            "failed_cases": sum(not item["passed_automated_checks"] for item in records),
            "source_sha256_begin": before, "source_sha256_end": after, "source_unchanged": before == after,
            "semantic_quality_passed": None,
            "note": "Six synthetic targeted examples, not a representative quality estimate. Offline checks do NOT evaluate semantics. Manual questions/reasons still need review. Heldout labels mean newly authored cases not used in the earlier documented evaluation; repeated tuning invalidates that status.",
            "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Opt in to real paid AI calls; one analysis per selected case.")
    parser.add_argument("--case", action="append", help="Select case ID; repeat to choose several.")
    parser.add_argument("--split", choices=["regression", "heldout"], help="Run one authored set only.")
    parser.add_argument("--output", default=".qa/semantic-evaluation.json")
    args = parser.parse_args(argv)
    cases = load_cases()
    unknown = set(args.case or []) - {case["id"] for case in cases}
    if unknown:
        parser.error("Unknown case ID.")
    cases = [case for case in cases if (not args.case or case["id"] in args.case) and (not args.split or case["split"] == args.split)]
    if not cases:
        parser.error("No cases selected.")
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / ".qa").resolve()) or output.suffix != ".json":
        parser.error("Reports must be JSON files inside .qa/ only.")
    if output.exists():
        parser.error("Output already exists; choose a new report filename to preserve earlier evidence.")
    report = evaluate(cases, live=args.live)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("live_ai", "cases", "failed_cases", "source_unchanged", "semantic_quality_passed")}, ensure_ascii=True))
    print("Report: " + str(output))
    return 1 if report["failed_cases"] or not report["source_unchanged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
