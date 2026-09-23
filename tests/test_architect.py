"""Source integrity and agent workflow tests. No API credit is used here."""

import copy
import json
from types import SimpleNamespace

import pytest

from agent.architect import (
    AnalysisUnavailable, AnalysisValidationError, _input_preview, _run, analyze_brief,
    score_card_fields, validate_analysis,
)
from agent.architect_tools import FACETS, FIELDS, RUBRIC, get_rubric, verify_quotes
from agent.evidence import original_quote, resolve_spans, source_passages


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


def test_non_task_cannot_earn_points_but_original_words_are_preserved():
    raw = valid_result()
    raw["task_present"] = False
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["score"] == 0
    assert result["fields"]["context"] == DRAFT
    assert result["task_present"] is False


@pytest.mark.parametrize("status", ["missing", "unknown", "irrelevant", "contradictory", "unverifiable"])
def test_authentic_but_unusable_information_cannot_earn_points(status):
    raw = valid_result()
    raw["criteria"][0].update(status=status, level=4)
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["criteria"][0]["level"] == 0
    assert result["score"] == 0


def test_task_and_criterion_eligibility_flags_are_validated():
    raw = valid_result()
    raw["task_present"] = "false"
    with pytest.raises(AnalysisValidationError, match="boolean"):
        validate_analysis(raw, DRAFT, {}, "en")
    raw["task_present"] = True
    raw["criteria"][0]["status"] = "looks fine"
    with pytest.raises(AnalysisValidationError, match="status"):
        validate_analysis(raw, DRAFT, {}, "en")


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


def test_cross_answer_passages_can_supply_a_second_relevant_field():
    raw = valid_result()
    answer = "Contact mentor@example.org. We meet online every Friday."
    raw["fields"].update(contact=answer, interaction_format="We meet online every Friday.")
    result = validate_analysis(raw, DRAFT, {"contact": answer}, "en")
    assert result["fields"]["interaction_format"] == "We meet online every Friday."
    assert {"field": "interaction_format", "quote": "We meet online every Friday.", "source": "answers.contact"} in result["evidence"]


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


def test_quote_verification_is_source_scoped_not_destination_scoped():
    sources = {"draft": DRAFT, "answers.contact": "mentor@example.org"}
    assert verify_quotes([{"field": "context", "source": "draft", "quote": "Kazakh-language textbooks"}], sources)["valid"]
    assert verify_quotes([{"field": "contact", "source": "answers.contact", "quote": "mentor@example.org"}], sources)["valid"]
    assert not verify_quotes([{"field": "contact", "source": "answers.unknown", "quote": "mentor@example.org"}], sources)["valid"]
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
    responses = iter([SimpleNamespace(output=calls, output_text=""), SimpleNamespace(output=[], output_text=json.dumps(raw)), SimpleNamespace(output=[], output_text=json.dumps(raw))])
    def create(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        return next(responses)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = _run(client, "test-model", DRAFT, {}, "en")
    assert result["mode"] == "ai"
    assert len(requests) == 3  # Tool round, candidate, bounded semantic audit.
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


def test_whitespace_mapping_preserves_original_characters():
    source = "Constraints:\n- no student names;\n- two weeks."
    assert original_quote("Constraints: - no student names; - two weeks.", source) == source
    assert original_quote("Constraints: no student names; two weeks.", source) is None


def test_disjoint_passages_are_individually_grounded():
    source = "We need a paper checklist. Data lives in CSV. No names may be collected."
    spans = resolve_spans("We need a paper checklist.\nNo names may be collected.", {"draft": source})
    assert [item["quote"] for item in spans] == ["We need a paper checklist.", "No names may be collected."]
    with pytest.raises(ValueError):
        resolve_spans("We need a paper checklist and no names may be collected.", {"draft": source})


@pytest.mark.parametrize("source,quote", [
    ("Do not collect student names.", "collect student names"),
    ("We do not\ncollect student names.", "collect student names"),
    ("We cannot collect phone numbers.", "collect phone numbers"),
    ("We mustn't collect student names.", "collect student names"),
    ("Запрещено собирать телефоны.", "собирать телефоны"),
    ("Сбор телефонов запрещён.", "Сбор телефонов"),
    ("Нельзя собирать телефоны студентов.", "собирать телефоны студентов"),
    ("Не используйте персональные данные.", "используйте персональные данные"),
    ("Автоматты бағалау қажет емес.", "Автоматты бағалау"),
])
def test_excerpts_must_not_cut_away_negative_qualifier(source, quote):
    with pytest.raises(ValueError):
        resolve_spans(quote, {"draft": source})
    assert resolve_spans(source, {"draft": source})[0]["quote"] == source


def test_explicit_clear_wins_even_over_a_compound_answer():
    raw = valid_result()
    answer = "Contact mentor@example.org. We meet every Friday."
    raw["fields"].update(contact=answer, interaction_format="We meet every Friday.")
    with pytest.raises(AnalysisValidationError, match="preserve"):
        validate_analysis(raw, DRAFT, {"contact": answer, "interaction_format": ""}, "en")


def test_multispan_field_retains_each_original_source():
    raw = valid_result()
    draft = DRAFT + " No student names may be collected."
    answer = "We need the checklist within two weeks."
    raw["fields"].update(need=answer, constraints="No student names may be collected.\nWe need the checklist within two weeks.")
    result = validate_analysis(raw, draft, {"need": answer}, "en")
    quotes = [item for item in result["evidence"] if item["field"] == "constraints"]
    assert len(quotes) == 2
    assert {item["source"] for item in quotes} == {"draft", "answers.need"}


def test_long_offline_draft_does_not_exceed_card_field_limit():
    draft = "This is a supplied business situation. " * 160
    result = analyze_brief(draft, offline=True, language="en")
    assert len(result["fields"]["context"]) == 4000
    assert result["fields"]["context"] == draft[:4000]
    assert len(result["warnings"]) == 2


def test_safe_diagnostic_metadata_does_not_contain_source():
    error = AnalysisUnavailable("A safe message", code="validation_failed", stage="audit")
    assert error.code == "validation_failed"
    assert error.stage == "audit"
    assert len(error.diagnostic_id) == 12


def test_failed_preliminary_quotes_do_not_discard_valid_final_card():
    good = valid_result()
    calls = [SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=name)
             for name, args in [("get_readiness_rubric", {}), ("verify_user_evidence", {"claims": [{"field": "data", "quote": "Invented", "source": "draft"}]})]]
    response = SimpleNamespace(output=[], output_text=json.dumps(good))
    responses = iter([SimpleNamespace(output=calls, output_text=""), response, response, response, response])
    result = _run(SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: next(responses))), "test-model", DRAFT, {}, "en")
    assert result["fields"]["context"] == DRAFT
    assert any(item["tool"] == "semantic_audit" for item in result["trace"])


def test_a_second_invalid_repair_is_not_retried_indefinitely():
    bad = valid_result()
    bad["fields"]["data"] = "Invented information"
    calls = [SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=name)
             for name, args in [("get_readiness_rubric", {}), ("verify_user_evidence", {"claims": []})]]
    requests = []
    responses = iter([SimpleNamespace(output=calls, output_text=""), SimpleNamespace(output=[], output_text=json.dumps(bad)), SimpleNamespace(output=[], output_text=json.dumps(bad))])
    def create(**kwargs):
        requests.append(kwargs)
        return next(responses)
    with pytest.raises(AnalysisValidationError, match="repair_failed"):
        _run(SimpleNamespace(responses=SimpleNamespace(create=create)), "test-model", DRAFT, {}, "en")
    assert len(requests) == 3


def coverage_result(draft, answers=None, assignment=None):
    raw = valid_result()
    raw.pop("fields")
    raw.pop("evidence")
    raw["title"] = ""
    passages = source_passages({"draft": draft, **{f"answers.{key}": value for key, value in (answers or {}).items()}})
    raw["coverage"] = [{"source_id": item["id"], "fields": (assignment or {}).get(item["id"], ["context"])} for item in passages]
    raw["contradictions"] = []
    for criterion in raw["criteria"]:
        criterion.pop("evidence")
        criterion["level"] = 0
    return raw


def test_passage_id_grounding_preserves_negative_clause_without_model_retyping():
    draft = "Teachers review essays. Автоматты бағалау қажет емес."
    raw = coverage_result(draft, assignment={"s1": ["context", "users"], "s2": ["constraints"]})
    result = validate_analysis(raw, draft, {}, "en")
    assert result["fields"]["users"] == "Teachers review essays."
    assert result["fields"]["constraints"] == "Автоматты бағалау қажет емес."
    assert verify_quotes(result["evidence"], {"draft": draft})["valid"]


def test_coverage_cannot_silently_skip_or_invent_passages():
    raw = coverage_result(DRAFT)
    raw["coverage"] = []
    with pytest.raises(AnalysisValidationError, match="every source"):
        validate_analysis(raw, DRAFT, {}, "en")
    raw["coverage"] = [{"source_id": "unknown", "fields": ["data"]}]
    with pytest.raises(AnalysisValidationError, match="unknown"):
        validate_analysis(raw, DRAFT, {}, "en")


def test_coverage_cross_answer_and_authoritative_clear():
    answer = "Contact mentor@example.org. Meet every Friday."
    answers = {"contact": answer, "interaction_format": ""}
    raw = coverage_result(DRAFT, answers, {"s1": ["context"], "s2": ["contact"], "s3": ["interaction_format"]})
    result = validate_analysis(raw, DRAFT, answers, "en")
    assert result["fields"]["contact"] == answer
    assert result["fields"]["interaction_format"] == ""
    answers.pop("interaction_format")
    result = validate_analysis(raw, DRAFT, answers, "en")
    assert result["fields"]["interaction_format"] == "Meet every Friday."


def test_source_supported_conflict_forces_only_affected_criterion_zero():
    draft = "The report is due tomorrow. The data arrives next week."
    raw = coverage_result(draft, assignment={"s1": ["context", "constraints"], "s2": ["constraints", "data"]})
    raw["contradictions"] = [{"source_ids": ["s1", "s2"], "criteria": ["constraints"], "description": "The data arrives after the report deadline."}]
    for item in raw["criteria"]:
        if item["key"] in {"data", "constraints"}:
            item["level"] = 3
            item["next_step"] = "No action needed; the conditions are complete."
    result = validate_analysis(raw, draft, {}, "en")
    assert next(item["points"] for item in result["criteria"] if item["key"] == "constraints") == 0
    assert next(item["points"] for item in result["criteria"] if item["key"] == "data") == 15
    assert "Resolve the stated conflict" in next(item["next_step"] for item in result["criteria"] if item["key"] == "constraints")
    assert next(item["next_step"] for item in result["criteria"] if item["key"] == "data") == "No action needed; the conditions are complete."
    assert result["warnings"] == ["The data arrives after the report deadline."]


def test_maximum_input_source_packet_is_bounded_and_keeps_all_tokens():
    draft = "A. " * 4000
    answers = {field: "B. " * 1000 for field in list(FIELDS)[1:9]}
    passages = source_passages({"draft": draft, **{f"answers.{key}": value for key, value in answers.items()}})
    assert len(draft) == 12000
    assert sum(map(len, answers.values())) == 24000
    assert len(passages) <= 64
    assert sum(item["quote"].count("A.") for item in passages) == 4000
    assert sum(item["quote"].count("B.") for item in passages) == 8000
    assert len(json.dumps(passages).encode("utf-8")) < 80000


def test_offline_reserves_total_budget_without_truncating_explicit_answers():
    answers = {field: "Supplied fact. " * 200 for field in list(FIELDS)[2:10]}
    assert sum(map(len, answers.values())) == 24000
    result = analyze_brief(DRAFT, answers, "en", offline=True)
    assert sum(map(len, result["fields"].values())) <= 24000
    assert all(result["fields"][key] == value.strip() for key, value in answers.items())


def test_overlong_explicit_title_fails_before_api():
    with pytest.raises(ValueError, match="180"):
        analyze_brief(DRAFT, {"title": "x" * 181}, "en")


def test_coverage_does_not_split_negation_from_a_wrapped_line():
    draft = "We do not\ncollect student names. Teachers review the checklist."
    passages = source_passages({"draft": draft})
    assert len(passages) == 2
    assert passages[0]["quote"] == "We do not\ncollect student names."
    raw = coverage_result(draft, assignment={"s1": ["constraints"], "s2": ["users"]})
    result = validate_analysis(raw, draft, {}, "en")
    assert result["fields"]["constraints"] == "We do not\ncollect student names."


def test_duplicate_passage_labels_merge_without_losing_a_fact():
    raw = coverage_result(DRAFT)
    raw["coverage"].append({"source_id": "s1", "fields": ["users"]})
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["fields"]["context"] == result["fields"]["users"] == DRAFT


def test_empty_field_positive_level_is_safely_zeroed():
    raw = valid_result()
    raw["criteria"][1].pop("evidence")
    raw["criteria"][1]["level"] = 3
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert result["criteria"][1]["points"] == 0


def test_complete_criterion_empty_next_step_gets_confirmation_not_failure():
    raw = valid_result()
    raw["fields"]["need"] = DRAFT
    raw["criteria"][0].update(level=4, next_step="")
    result = validate_analysis(raw, DRAFT, {}, "en")
    assert "Confirm" in result["criteria"][0]["next_step"]


def test_derived_evidence_can_exceed_the_tool_claim_limit():
    claims = [{"field": "context", "source": "draft", "quote": DRAFT} for _ in range(50)]
    assert verify_quotes(claims, {"draft": DRAFT})["valid"]
    assert not verify_quotes(claims, {"draft": DRAFT}, max_claims=40)["valid"]


def assessed_result(draft, assignment=None):
    raw = coverage_result(draft, assignment=assignment)
    for criterion in raw["criteria"]:
        criterion.update(status="usable", assessment=[{
            "id": key, "source_ids": [], "state": "missing",
            "observation": "This specific requirement is not supplied.",
            "next_step": "Supply this requirement before beginning work.",
        } for key in FACETS[criterion["key"]]])
    return raw


@pytest.mark.parametrize("states,level", [
    (("met", "met"), 4), (("met", "partial"), 3),
    (("met", "missing"), 2), (("partial", "missing"), 1),
    (("partial", "partial"), 1), (("missing", "missing"), 0),
    (("met", "blocked"), 0),
])
def test_fixed_requirements_determine_level_not_arbitrary_holistic_score(states, level):
    raw = assessed_result(DRAFT)
    criterion = next(item for item in raw["criteria"] if item["key"] == "data")
    criterion.update(level=4, reason="Invented holistic reason must not survive.")
    for facet, state in zip(criterion["assessment"], states):
        facet.update(state=state, source_ids=[] if state == "missing" else ["s1"], observation="Source-backed assessment of the actual information.")
    result = validate_analysis(raw, DRAFT, {}, "en")
    actual = next(item for item in result["criteria"] if item["key"] == "data")
    assert actual["level"] == level
    assert "Invented" not in actual["reason"]


def test_requirement_evidence_repairs_material_coverage_without_rewriting_source():
    draft = "Volunteers revise the existing safety handbook. The manager emails it today."
    raw = assessed_result(draft, {"s1": ["expected_result"], "s2": ["contact"]})
    data = next(item for item in raw["criteria"] if item["key"] == "data")
    for facet, source_id in zip(data["assessment"], ["s1", "s2"]):
        facet.update(state="met", source_ids=[source_id], observation="The material and handoff are specified.", next_step="Confirm the supplied material and handoff.")
    result = validate_analysis(raw, draft, {}, "en")
    assert "existing safety handbook" in result["fields"]["data"]
    assert "emails it today" in result["fields"]["data"]
    assert next(item["points"] for item in result["criteria"] if item["key"] == "data") == 20
    assert next(item["next_step"] for item in result["criteria"] if item["key"] == "data") == "Confirm this information before publishing."
    question = next(item for item in result["questions"] if item["field"] == "data")
    assert question["max_points"] == 0 and question["priority"] == "medium"


def test_late_data_dependency_zeroes_data_even_with_named_material():
    draft = "The report is due Monday. The source spreadsheet arrives Friday after that deadline."
    raw = assessed_result(draft, {"s1": ["constraints"], "s2": ["data"]})
    data = next(item for item in raw["criteria"] if item["key"] == "data")
    data["assessment"][0].update(state="met", source_ids=["s2"], observation="The spreadsheet is named.")
    data["assessment"][1].update(state="blocked", source_ids=["s1", "s2"], observation="The spreadsheet arrives after the report deadline.", next_step="Agree a feasible handoff date or project deadline.")
    result = validate_analysis(raw, draft, {}, "en")
    actual = next(item for item in result["criteria"] if item["key"] == "data")
    assert actual["points"] == 0
    assert actual["next_step"] == "Agree a feasible handoff date or project deadline."


@pytest.mark.parametrize("defect", ["unknown_id", "no_evidence", "duplicate_requirement", "missing_with_evidence"])
def test_invalid_requirement_assessments_are_rejected(defect):
    raw = assessed_result(DRAFT)
    assessment = raw["criteria"][0]["assessment"]
    if defect == "unknown_id":
        assessment[0].update(state="met", source_ids=["s999"])
    elif defect == "no_evidence":
        assessment[0].update(state="met", source_ids=[])
    elif defect == "duplicate_requirement":
        assessment[1] = copy.deepcopy(assessment[0])
    else:
        assessment[0].update(state="missing", source_ids=["s1"])
    with pytest.raises(AnalysisValidationError, match="assessment"):
        validate_analysis(raw, DRAFT, {}, "en")


def test_requirement_mapping_cannot_override_an_explicit_cleared_field():
    raw = assessed_result(DRAFT)
    users = next(item for item in raw["criteria"] if item["key"] == "users")
    for facet in users["assessment"]:
        facet.update(state="met", source_ids=["s1"], observation="The original passage names the users.")
    result = validate_analysis(raw, DRAFT, {"users": ""}, "en")
    assert result["fields"]["users"] == ""
    assert next(item["points"] for item in result["criteria"] if item["key"] == "users") == 0


def test_existing_input_inventory_is_separate_from_future_deliverable():
    draft = "Revise the existing shift manual. Produce a new checklist."
    raw = coverage_result(draft, assignment={"s1": ["need"], "s2": ["expected_result"]})
    raw["coverage"][0]["contains_existing_material"] = True
    raw["coverage"][1]["contains_existing_material"] = False
    result = validate_analysis(raw, draft, {}, "en")
    assert result["fields"]["data"] == "Revise the existing shift manual."
    assert "Produce a new checklist." not in result["fields"]["data"]


def test_existing_input_inventory_respects_explicit_data_clear():
    raw = coverage_result(DRAFT)
    raw["coverage"][0]["contains_existing_material"] = True
    result = validate_analysis(raw, DRAFT, {"data": ""}, "en")
    assert result["fields"]["data"] == ""


def test_existing_material_flag_must_be_boolean_not_a_truthy_string():
    raw = coverage_result(DRAFT)
    raw["coverage"][0]["contains_existing_material"] = "false"
    with pytest.raises(AnalysisValidationError, match="boolean"):
        validate_analysis(raw, DRAFT, {}, "en")
