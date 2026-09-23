"""Synthetic semantic fixtures and evaluator safety; never call a provider."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import pytest

from agent.architect import analyze_brief
from agent.architect_tools import FIELDS, RUBRIC
from scripts import evaluate_semantics as evaluation
from server.app import AnalyzeInput

CASES = evaluation.load_cases()


def test_six_new_synthetic_cases_cover_documented_failure_classes():
    assert len(CASES) == 6 and len({case["id"] for case in CASES}) == 6
    assert {case["language"] for case in CASES} == {"ru", "kk", "en"}
    assert {case["split"] for case in CASES} == {"regression", "heldout"}
    assert sum(case["split"] == "heldout" for case in CASES) == 3
    assert len({case["failure_class"] for case in CASES}) == 6
    assert all(case["synthetic"] is True and len(case["manual_review"]) >= 2 for case in CASES)
    assert all("score_range" not in case and "expected_score" not in case for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_semantic_fixture_inputs_and_expectations_are_source_grounded(case):
    AnalyzeInput(draft=case["draft"], answers=case["answers"], language=case["language"])
    assert set(case["answers"]) <= set(FIELDS)
    sources = "\n".join([case["draft"], *case["answers"].values()]).casefold()
    for field, fragments in case["required_field_facts"].items():
        assert field in FIELDS and fragments
        assert all(fragment.casefold() in sources for fragment in fragments)
    for key, rule in case["criterion_rules"].items():
        assert key in RUBRIC
        assert set(rule) <= {"zero", "min_level"}
        assert rule.get("zero") is True or rule.get("min_level") == 1
    emails = re.findall(r"[\w.+-]+@[\w.-]+", sources)
    assert all(email.endswith("@example.org") for email in emails)


def test_default_offline_runs_only_contract_checks_not_semantic_claims():
    calls = []
    def local(draft, answers, language, *, offline):
        assert offline is True
        calls.append(1)
        return analyze_brief(draft, answers, language, offline=True)
    report = evaluation.evaluate(CASES, analyzer=local)
    assert len(calls) == 6 and report["live_ai"] is False and report["failed_cases"] == 0
    assert report["source_unchanged"] and report["semantic_quality_passed"] is None
    assert all(not item["semantic_checks_executed"] and item["semantic_checks"] == {} for item in report["records"])
    assert all(check["status"] == "not_reviewed" for item in report["records"] for check in item["manual_review"])


def test_live_checks_detect_document_omission_and_unavailable_data_credit_without_exact_score():
    document = CASES[0]
    local = analyze_brief(document["draft"], document["answers"], document["language"], offline=True)
    local["mode"] = "ai"
    checks = evaluation.check_result(document, local, live=True)
    assert checks["semantic_checks"]["facts:data"] is False
    assert checks["semantic_checks"]["minimum:data"] is False
    unavailable = CASES[1]
    result = analyze_brief(unavailable["draft"], {}, unavailable["language"], offline=True)
    result["mode"] = "ai"
    next(item for item in result["criteria"] if item["key"] == "data").update(level=2, points=10)
    checked = evaluation.check_result(unavailable, result, live=True)
    assert checked["semantic_checks"]["zero:data"] is False
    assert checked["contract_checks"]["score_arithmetic"] is False


def test_explicit_answers_and_all_zero_attack_are_separate_checks():
    case = CASES[3]
    result = analyze_brief(case["draft"], case["answers"], case["language"], offline=True)
    result["fields"]["contact"] = ""
    assert not evaluation.check_result(case, result, live=False)["contract_checks"]["explicit_answers_preserved"]
    attack = CASES[2]
    result = analyze_brief(attack["draft"], {}, attack["language"], offline=True)
    result["mode"] = "ai"
    assert not evaluation.check_result(attack, result, live=True)["semantic_checks"]["all_criteria_zero"]


def test_provider_errors_never_copy_exception_text_or_cause():
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET_API_KEY provider response personal draft Authorization Bearer xyz")
    report = evaluation.evaluate(CASES[:1], live=True, analyzer=broken)
    assert report["failed_cases"] == 1 and report["records"][0]["error"]["code"] == "evaluation_failed"
    serialized = json.dumps(report)
    assert "SECRET_API_KEY" not in serialized and "Bearer" not in serialized


def test_reports_omit_trace_and_source_drift_invalidates_run(monkeypatch):
    version = iter([{"file": "before"}, {"file": "after"}])
    monkeypatch.setattr(evaluation, "source_hashes", lambda: next(version))
    def local(draft, answers, language, **kwargs):
        result = analyze_brief(draft, answers, language, offline=True)
        result["trace"] = [{"secret": "RAW_PROVIDER_BODY"}]
        return result
    report = evaluation.evaluate(CASES[:1], analyzer=local)
    assert not report["source_unchanged"]
    assert "RAW_PROVIDER_BODY" not in json.dumps(report)


@pytest.mark.parametrize("output", ["README.md", ".qa/../outside.json", ".qa/report.txt"])
def test_output_must_stay_inside_qa_json_before_any_analysis(output, monkeypatch):
    monkeypatch.setattr(evaluation, "evaluate", lambda *args, **kwargs: pytest.fail("Must reject before analysis"))
    with pytest.raises(SystemExit) as stopped:
        evaluation.main(["--output", output])
    assert stopped.value.code == 2


def test_cli_default_never_opts_in_to_paid_analysis_and_saves_report(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    def fake(cases, *, live):
        assert live is False
        return {"live_ai": False, "cases": len(cases), "failed_cases": 0,
                "source_unchanged": True, "semantic_quality_passed": None}
    monkeypatch.setattr(evaluation, "load_cases", lambda: copy.deepcopy(CASES))
    monkeypatch.setattr(evaluation, "evaluate", fake)
    assert evaluation.main(["--output", ".qa/report.json"]) == 0
    saved = json.loads((tmp_path / ".qa/report.json").read_text(encoding="utf-8"))
    assert saved["live_ai"] is False and saved["cases"] == 6
    with pytest.raises(SystemExit) as stopped:
        evaluation.main(["--output", ".qa/report.json"])
    assert stopped.value.code == 2
