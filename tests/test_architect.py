"""Source integrity and agent workflow tests. No API credit is used here."""

import copy
import json
from types import SimpleNamespace

import pytest

from agent.architect import (
    AnalysisUnavailable, AnalysisValidationError, _input_preview, _run, analyze_brief,
    score_card_fields, validate_analysis,
)
from agent.architect_tools import FIELDS, RUBRIC, get_rubric, verify_quotes


DRAFT = "Library students cannot find Kazakh-language textbooks in the existing catalog."


def valid_result():
    fields = {key: "" for key in FIELDS}
    fields.update(title="Kazakh-language textbooks", context=DRAFT)
    return {
        "summary": "Students cannot find Kazakh-language textbooks. Available catalog data needs clarification.",
        "fields": fields,
        "evidence": [{"field": key, "quote": value, "source": "draft"} for key, value in fields.items() if value],
        "questions": [{"id": field, "field": field, "question": question, "why": "The team needs a concrete starting point.", "answer_hint": "State the facts already known.", "priority": "high", "max_points": 20} for field, question in [
            ("data", "Which catalog records can the library share?"),
            ("success_criteria", "How will students test whether textbook search improves?"),
            ("expected_result", "What should the team hand over to the library?"),
        ]],
        "criteria": [{"key": key, "level": 1 if key == "context" else 0, "evidence": DRAFT if key == "context" else "", "reason": "The current problem is described." if key == "context" else "No information supplied.", "next_step": "State the missing practical detail."} for key in RUBRIC],
        "warnings": [],
    }


def test_grounded_contract_and_question_points():
    result = validate_analysis(valid_result(), DRAFT, {}, "en")
    assert result["score"] == 5
    assert len(result["criteria"]) == 7
    assert sum(item["weight"] for item in result["criteria"]) == 100
    assert result["questions"][1]["max_points"] == 15


def test_missing_redundant_evidence_is_derived_from_verified_fields():
    raw = valid_result()
    raw["evidence"] = []
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert len(result["evidence"]) == 2
    assert verify_quotes(result["evidence"], {"draft": DRAFT})["valid"]


def test_criterion_evidence_is_attached_from_fixed_field_mapping():
    raw = valid_result()
    for criterion in raw["criteria"]:
        criterion.pop("evidence")
    raw.pop("evidence")
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["criteria"][0]["evidence"] == DRAFT
    assert result["criteria"][1]["evidence"] == ""


@pytest.mark.parametrize("field,value", [("data", "10,000 MARC records"), ("contact", "contact@example.org")])
def test_invented_fields_rejected(field, value):
    raw = valid_result()
    raw["fields"][field] = value
    with pytest.raises(AnalysisValidationError):
        validate_analysis(raw, DRAFT, {})


def test_paraphrased_title_is_replaced_by_safe_source_label():
    raw = valid_result()
    raw["fields"]["title"] = "City Library AI Platform"
    raw["evidence"] = []
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["fields"]["title"] in DRAFT
    assert "AI Platform" not in result["fields"]["title"]


def test_same_field_answer_overrides_draft_exactly():
    raw = valid_result()
    answers = {"context": "The new catalog works; students now need help with holds."}
    with pytest.raises(AnalysisValidationError, match="preserve"):
        validate_analysis(raw, DRAFT, answers)


def test_explicit_clear_cannot_resurrect_a_draft_fact():
    draft = DRAFT + " Contact mentor@example.org."
    raw = valid_result()
    raw["fields"]["contact"] = "mentor@example.org"
    raw["evidence"] = []
    with pytest.raises(AnalysisValidationError, match="preserve"):
        validate_analysis(raw, draft, {"contact": ""}, "en")
    raw["fields"]["contact"] = ""
    result = validate_analysis(raw, draft, {"contact": ""}, "en")
    assert result["fields"]["contact"] == ""
    assert not any(item["field"] == "contact" for item in result["evidence"])


def test_offline_preserves_explicitly_cleared_title_and_context():
    result = analyze_brief(DRAFT, {"title": "", "context": "", "contact": ""}, offline=True)
    assert result["fields"]["title"] == result["fields"]["context"] == result["fields"]["contact"] == ""
    assert result["score"] == 0


def test_answer_cannot_be_assigned_to_unrelated_field():
    raw = valid_result()
    raw["fields"]["constraints"] = "We can export catalog records."
    with pytest.raises(AnalysisValidationError):
        validate_analysis(raw, DRAFT, {"data": "We can export catalog records."})


def test_wrong_score_evidence_is_rejected():
    raw = valid_result()
    raw["criteria"][1].update(level=4, evidence="Library students")
    with pytest.raises(AnalysisValidationError, match="corresponding"):
        validate_analysis(raw, DRAFT, {})


def test_duplicate_questions_are_rejected():
    raw = valid_result()
    raw["questions"][1] = copy.deepcopy(raw["questions"][0])
    with pytest.raises(AnalysisValidationError, match="distinct"):
        validate_analysis(raw, DRAFT, {})


def test_quote_verification_is_exact_and_field_scoped():
    sources = {"draft": DRAFT, "answers.contact": "mentor@example.org"}
    assert verify_quotes([{"field": "context", "source": "draft", "quote": "Kazakh-language textbooks"}], sources)["valid"]
    assert not verify_quotes([{"field": "data", "source": "answers.contact", "quote": "mentor@example.org"}], sources)["valid"]
    assert not verify_quotes([{"field": "context", "source": "draft", "quote": "kazakh-language textbooks"}], sources)["valid"]
    assert verify_quotes([{"field": "context", "source": "draft", "quote": '"Kazakh-language textbooks"'}], sources)["valid"]
    assert verify_quotes([{"field": "data", "source": "draft", "quote": ""}], sources) == {"valid": True, "checks": []}


def test_length_does_not_increase_unreviewed_score():
    short = {"data": "CSV export"}
    long = {"data": "CSV export " * 200}
    assert score_card_fields(short)["score"] == score_card_fields(long)["score"] == 5


def test_short_precise_review_can_receive_full_credit():
    fields = {"constraints": "Two weeks; no student identifiers."}
    review = [{"key": "constraints", "level": 4, "evidence": fields["constraints"], "reason": "Deadline and data boundary are explicit.", "next_step": "Confirm these conditions."}]
    assert score_card_fields(fields, review)["score"] == 10


def test_missing_half_of_compound_criterion_is_capped():
    fields = {"contact": "mentor@example.org"}
    review = [{"key": "contact", "level": 4, "evidence": fields["contact"], "reason": "Contact is usable.", "next_step": "Agree feedback cadence."}]
    assert score_card_fields(fields, review)["score"] == 5


def test_stale_review_does_not_grant_full_points():
    review = [{"key": "data", "level": 4, "evidence": "Approved CSV export", "reason": "Available.", "next_step": "Confirm."}]
    assert score_card_fields({"data": "We might have records"}, review)["score"] == 5


def test_unknown_and_contradictory_information_earns_zero():
    assert score_card_fields({"data": "не знаю", "users": "unknown"})["score"] == 0
    review = [{"key": "constraints", "level": 0, "evidence": "", "reason": "Contradictory dates.", "next_step": "Choose a deadline."}]
    assert score_card_fields({"constraints": "Must finish tomorrow but may not start until next week."}, review)["score"] == 0


def test_full_validated_criteria_total_100():
    fields = {field: f"Source fact for {field}" for field in FIELDS}
    review = [{"key": key, "level": 4, "evidence": fields[rule["fields"][0]], "reason": "Complete.", "next_step": "Confirm."} for key, rule in RUBRIC.items()]
    assert score_card_fields(fields, review)["score"] == 100
    assert score_card_fields(fields, review, "en")["readiness"] == "Priority"


@pytest.mark.parametrize("language", ["ru", "kk", "en"])
def test_offline_explicit_and_grounded(language):
    result = analyze_brief(DRAFT, language=language, offline=True)
    assert result["mode"] == "offline"
    assert result["model"] is None
    assert result["warnings"]
    assert len(result["questions"]) >= 3
    assert result["fields"]["data"] == ""
    assert result["score"] <= 10
    assert verify_quotes(result["evidence"], {"draft": DRAFT})["valid"]


@pytest.mark.parametrize("draft", ["", "too short", "1234567890123456789", "!" * 30, "x" * 12001])
def test_invalid_drafts_fail_before_api(draft):
    with pytest.raises(ValueError):
        analyze_brief(draft)


def test_missing_key_never_silently_returns_offline(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AnalysisUnavailable, match="AI"):
        analyze_brief(DRAFT)


def test_model_selects_tools_and_receives_their_results():
    raw = valid_result()
    calls = [
        SimpleNamespace(type="function_call", name="get_readiness_rubric", arguments="{}", call_id="rubric"),
        SimpleNamespace(type="function_call", name="verify_user_evidence", arguments=json.dumps({"claims": raw["evidence"]}), call_id="evidence"),
    ]
    requests = []
    responses = iter([SimpleNamespace(output=calls, output_text=""), SimpleNamespace(output=[], output_text=json.dumps(raw))])
    def create(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        return next(responses)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = _run(client, "test-model", DRAFT, {}, "en")
    assert result["mode"] == "ai"
    assert len(requests) == 2
    outputs = [item for item in requests[1]["input"] if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert {item["call_id"] for item in outputs} == {"rubric", "evidence"}
    assert result["trace"][0]["tool"] == "get_readiness_rubric"
    assert result["trace"][0]["input_preview"] == "{}"
    assert requests[0]["tool_choice"] == "required"
    assert isinstance(requests[0]["tool_choice"], str)  # No forced function name.
    assert requests[0]["store"] is False


def test_input_audit_is_bounded_and_masks_key_shaped_values():
    result = _input_preview({"source": "x" * 1500})
    assert result["input_truncated"]
    assert result["input_preview"].endswith("[truncated]")
    assert len(result["input_preview"]) < 1250
    masked = _input_preview({"value": "sk-" + "a" * 32})
    assert "[REDACTED]" in masked["input_preview"]


def test_invalid_output_has_one_repair_only():
    good = valid_result()
    bad = copy.deepcopy(good)
    bad["fields"]["data"] = "Invented data"
    calls = [SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=name) for name, args in [("get_readiness_rubric", {}), ("verify_user_evidence", {"claims": good["evidence"]})]]
    responses = iter([SimpleNamespace(output=calls, output_text=""), SimpleNamespace(output=[], output_text=json.dumps(bad)), SimpleNamespace(output=[], output_text=json.dumps(good))])
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: next(responses)))
    result = _run(client, "test-model", DRAFT, {}, "en")
    assert any(item["tool"] == "repair_validation" for item in result["trace"])


def test_rubric_has_seven_business_criteria():
    rubric = get_rubric("kk")
    assert len(rubric["criteria"]) == 7
    assert sum(item["weight"] for item in rubric["criteria"]) == 100
