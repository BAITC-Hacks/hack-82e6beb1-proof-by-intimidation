import json
from types import SimpleNamespace

from agent.core import _personalized_questions


def test_questions_need_exact_draft_quote_and_distinct_criteria():
    draft = "Students cannot find Kazakh-language textbooks in the catalog."
    items = [
        {"field": "data", "quote": "Kazakh-language textbooks", "question": "Does the catalog tag Kazakh-language textbooks by language?"},
        {"field": "data", "quote": "the catalog", "question": "Can the team export the catalog?"},
        {"field": "success_criteria", "quote": "the catalog", "question": "How fast should students find a book in the catalog?"},
        {"field": "constraints", "quote": "private database", "question": "Can the team use the private database?"},
    ]
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: SimpleNamespace(output_text=json.dumps({"questions": items}))))
    questions = _personalized_questions(client, "test-model", draft, ["data", "success_criteria", "constraints"])
    assert len(questions) == 2
    assert "Kazakh-language textbooks" in questions[0]
