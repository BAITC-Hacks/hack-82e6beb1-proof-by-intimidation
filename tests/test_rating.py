from rating import calculate_rating, readiness_level


def complete_card():
    return {
        "context": "Есть проблема", "need": "Нужно решить", "users": "Студенты", "data": "CSV", "constraints": "2 недели",
        "expected_result": "Прототип", "success_criteria": "10 пользователей", "contact": "team@example.kz",
        "interaction_format": "Раз в неделю", "confirmed_fields": ["context", "need", "users", "data", "constraints", "expected_result", "success_criteria", "contact", "interaction_format"],
    }


def test_complete_confirmed_card_scores_100():
    assert calculate_rating(complete_card())["score"] == 100
    assert readiness_level(100) == "Приоритетная"


def test_unconfirmed_values_do_not_score():
    card = complete_card()
    card["confirmed_fields"] = []
    assert calculate_rating(card)["score"] == 0


def test_low_score_does_not_hide_readiness_level():
    assert readiness_level(39) == "Черновик"
