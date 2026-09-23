"""Validate that the jury's additional workflows are self-contained synthetic data."""

import json
from pathlib import Path

import pytest

from server.app import AnalyzeInput, ChallengeInput
from server.database import CARD_FIELDS


CASES = json.loads((Path(__file__).resolve().parents[1] / "data" / "acceptance_cases.json").read_text(encoding="utf-8"))


def test_acceptance_cases_cover_three_languages_and_distinct_problems():
    assert {case["language"] for case in CASES} == {"ru", "kk", "en"}
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert len({case["draft"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_acceptance_case_contains_valid_complete_confirmable_card(case):
    assert set(case["answers"]) == set(CARD_FIELDS)
    assert all(isinstance(text, str) and text.strip() for text in case["answers"].values())
    AnalyzeInput(draft=case["draft"], answers=case["answers"], language=case["language"])
    ChallengeInput(draft=case["draft"], fields=case["answers"], topic=case["topic"], confirmed=True)
    assert case["answers"]["contact"].endswith("@example.org")
    assert len(case["review_checks"]) >= 3
    for field, terms in case["field_terms"].items():
        assert field in CARD_FIELDS
        assert all(term.casefold() in case["answers"][field].casefold() for term in terms)
