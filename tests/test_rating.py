from agent.review import validate_review
from rating import SCORING_RULES, calculate_rating, readiness_level


def complete_card():
    return {
        "context": "Есть проблема", "need": "Нужно решить", "users": "Студенты", "data": "CSV", "constraints": "2 недели",
        "expected_result": "Прототип", "success_criteria": "10 пользователей", "contact": "team@example.kz",
        "interaction_format": "Раз в неделю", "confirmed_fields": ["context", "need", "users", "data", "constraints", "expected_result", "success_criteria", "contact", "interaction_format"],
    }


def test_vague_confirmed_card_does_not_get_100():
    assert calculate_rating(complete_card())["score"] < 50
    assert readiness_level(100) == "Приоритетная"


def test_unconfirmed_values_do_not_score():
    card = complete_card()
    card["confirmed_fields"] = []
    assert calculate_rating(card)["score"] == 0


def test_low_score_does_not_hide_readiness_level():
    assert readiness_level(39) == "Черновик"


def test_detailed_card_beats_generic_card():
    card = complete_card()
    card.update({
        "context": "В библиотеке первокурсники тратят 20 минут на поиск учебников на казахском языке в существующем каталоге.",
        "need": "Нужно добавить поиск по языку и показать наличие учебника до визита в библиотеку.",
        "data": "CSV выгрузка каталога из 500 записей: название, язык, автор; библиотекарь передаст обезличенную копию.",
        "expected_result": "Рабочий веб-прототип фильтра по языку и страница наличия книги.",
        "success_criteria": "Пять студентов найдут учебник на казахском языке менее чем за 2 минуты в тесте.",
    })
    assert calculate_rating(card)["score"] > calculate_rating(complete_card())["score"]


def test_unsupported_ai_quote_cannot_raise_rating():
    card = complete_card()
    baseline = calculate_rating(card)["score"]
    card["quality_review"] = {key: {"level": 4, "evidence": "Несуществующий факт", "reason": "Идеально", "next_step": ""} for key in SCORING_RULES}
    assert calculate_rating(card)["score"] == baseline


def test_quality_review_requires_exact_quote():
    raw = {"criteria": {"data": {"level": 4, "evidence": "секретная база", "reason": "Есть данные", "next_step": ""}}}
    assert validate_review(raw, {"data": "CSV"})["data"]["level"] == 0


def test_exact_quote_alone_cannot_claim_perfect_data_score():
    card = complete_card()
    card["data"] = "Есть CSV с примерами обращений студентов."
    card["quality_review"] = {"data": {"level": 4, "evidence": "CSV", "reason": "Данные готовы", "next_step": ""}}
    data = next(item for item in calculate_rating(card)["breakdown"] if item["key"] == "data")
    assert data["level"] == 2
    assert "доступ" in data["reason"]


def test_score_recalculates_after_confirmed_edit():
    card = complete_card()
    before = calculate_rating(card)["score"]
    card["data"] = "Библиотекарь передаст обезличенную CSV-выгрузку каталога: название, язык и наличие книги."
    after = calculate_rating(card)["score"]
    assert after > before
