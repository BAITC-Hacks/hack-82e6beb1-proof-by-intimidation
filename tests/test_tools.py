from agent.tools import analyze_draft, build_card, fallback_questions, propose_questions


def test_weak_draft_gets_at_least_three_questions():
    analysis = analyze_draft("Нужен полезный сервис для студентов")
    assert len(fallback_questions(analysis["missing_fields"])) >= 3
    assert propose_questions(analysis["missing_fields"])["fields_to_clarify"]


def test_card_contains_only_source_answers_or_draft():
    card = build_card("Нужен каталог", {"users": "Студенты", "data": "CSV"})["card"]
    assert card["users"] == "Студенты"
    assert card["data"] == "CSV"
    assert card["context"] == "Нужен каталог"
