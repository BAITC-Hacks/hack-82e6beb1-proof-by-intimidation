"""Public API acceptance tests: isolated databases; never call an external AI service."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("server.app")

FIELDS = {
    "title": "Find Kazakh library textbooks",
    "context": "Students cannot find Kazakh textbooks in the university's existing catalog.",
    "need": "Improve retrieval of the textbooks already held by the library.",
    "users": "First-year students searching by course title.",
    "data": "The library provides a synthetic CSV catalog with 100 sample records.",
    "constraints": "A two-week prototype without personal data or production integration.",
    "expected_result": "A working catalog search prototype with a reusable test collection.",
    "success_criteria": "At least 8 of 10 students find a textbook in under one minute in a usability test.",
    "contact": "library@example.kz",
    "interaction_format": "The librarian joins a 30-minute Zoom call every week.",
}


def fake_score(fields, review=None, language="ru"):
    # Deliberately different trusted/local outcomes exercise the API trust boundary.
    return {
        "score": 80 if review else 25,
        "readiness": "ready" if review else "draft",
        "criteria": review or [{"key": "context", "weight": 20, "level": 1, "points": 5}],
    }


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "score_card_fields", fake_score)
    return api.create_app(tmp_path / "challenges.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app) as browser:
        yield browser


def create_challenge(client, **overrides):
    payload = {
        "draft": "Students cannot find their Kazakh textbooks in the university catalog.",
        "fields": FIELDS, "topic": "Education", "confirmed": True, "language": "en",
    }
    payload.update(overrides)
    return client.post("/api/challenges", json=payload)


def propose(client, challenge_id, **overrides):
    payload = {
        "team_id": "team1", "idea": "Improve catalog search using a language-aware index.",
        "plan": "Inspect the supplied data, implement search and test ten retrieval cases.",
        "deadline": "Two weeks", "link": "https://example.com/library-prototype",
    }
    payload.update(overrides)
    return client.post(f"/api/challenges/{challenge_id}/proposals", json=payload)


def test_seed_catalog_is_complete_sorted_and_read_only(client):
    result = client.get("/api/bootstrap")
    assert result.status_code == 200
    state = result.json()
    assert len(state["challenges"]) >= 5
    assert len(state["teams"]) >= 5
    assert len(state["drafts"]) >= 5
    assert sum(task["proposal_count"] for task in state["challenges"]) >= 5
    assert all(not task["is_owner"] for task in state["challenges"])
    assert all("owner" not in task for task in state["challenges"])
    assert all(task["score_source"] == "sample" and not task["analysis_fields_changed"] for task in state["challenges"])
    scores = [task["score"] for task in state["challenges"]]
    assert scores == sorted(scores, reverse=True)
    assert client.patch("/api/challenges/t1", json={"fields": {"title": "Hijack"}, "confirmed": True}).status_code == 403
    assert "HttpOnly" in result.headers["set-cookie"]


def test_full_manual_journey_and_once_only_progress(client):
    created = create_challenge(client)
    assert created.status_code == 201
    task = created.json()
    assert task["is_owner"] and task["score"] == 25
    assert task["score_source"] == "local" and task["analysis_fields_changed"] is False
    first = propose(client, task["id"])
    second = propose(client, task["id"], team_id="team2")
    assert first.status_code == second.status_code == 201
    proposal = first.json()
    assert proposal["status"] == "submitted" and proposal["points"] == 0
    milestone = {"title": "Search prototype", "evidence": "The supplied prototype was reviewed against ten retrieval examples."}
    assert client.post(f"/api/proposals/{proposal['id']}/milestones", json=milestone).status_code == 409
    assert client.patch(f"/api/proposals/{proposal['id']}", json={"status": "accepted"}).status_code == 200
    # Multiple teams can be accepted; the business makes every decision.
    assert client.patch(f"/api/proposals/{second.json()['id']}", json={"status": "accepted"}).status_code == 200
    completed = client.post(f"/api/proposals/{proposal['id']}/milestones", json=milestone)
    assert completed.status_code == 201
    assert completed.json()["points"] == 10
    assert client.post(f"/api/proposals/{proposal['id']}/milestones", json=milestone).status_code == 409
    assert client.patch(f"/api/proposals/{proposal['id']}", json={"status": "rejected"}).status_code == 409
    refreshed = client.get(f"/api/challenges/{task['id']}").json()
    assert refreshed["proposal_count"] == 2 and len(refreshed["progress"]) == 1
    assert refreshed["progress"][0]["points"] == 10


def test_other_browser_can_propose_but_cannot_select_or_edit(app, client):
    challenge = create_challenge(client).json()
    with TestClient(app) as visitor:
        assert visitor.get(f"/api/challenges/{challenge['id']}").json()["is_owner"] is False
        proposal = propose(visitor, challenge["id"]).json()
        assert visitor.patch(f"/api/challenges/{challenge['id']}", json={
            "fields": {"title": "Changed by somebody else"}, "confirmed": True,
        }).status_code == 403
        assert visitor.patch(f"/api/proposals/{proposal['id']}", json={"status": "accepted"}).status_code == 403
        assert visitor.post(f"/api/proposals/{proposal['id']}/milestones", json={
            "title": "Pretend milestone", "evidence": "Somebody else attempts to award this team points.",
        }).status_code == 403
    assert client.patch(f"/api/proposals/{proposal['id']}", json={"status": "rejected"}).status_code == 200


def test_unconfirmed_cards_and_client_scores_are_rejected(client):
    assert create_challenge(client, confirmed=False).status_code == 422
    assert create_challenge(client, score=100).status_code == 422
    assert create_challenge(client, fields={**FIELDS, "quality_review": "trust me"}).status_code == 422
    assert create_challenge(client, fields={**FIELDS, "title": ""}).status_code == 422
    assert create_challenge(client, fields={**FIELDS, "context": "", "need": ""}).status_code == 422


def test_edit_recalculates_and_rejects_stale_version(client):
    task = create_challenge(client).json()
    edited = client.patch(f"/api/challenges/{task['id']}", json={
        "fields": {"title": "Updated catalog task"}, "confirmed": True, "version": 1,
    })
    assert edited.status_code == 200
    assert edited.json()["version"] == 2
    assert edited.json()["fields"]["context"] == FIELDS["context"]
    assert client.patch(f"/api/challenges/{task['id']}", json={
        "fields": {"title": "Stale overwrite"}, "confirmed": True, "version": 1,
    }).status_code == 409
    assert client.get(f"/api/challenges/{task['id']}").json()["title"] == "Updated catalog task"


@pytest.mark.parametrize("link", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.com", "not a url"])
def test_unsafe_prototype_links_are_rejected(client, link):
    assert propose(client, "t4", link=link).status_code == 422


def test_low_rating_tasks_accept_unlimited_proposals(client):
    for _ in range(3):
        assert propose(client, "t4").status_code == 201
    assert client.get("/api/challenges/t4").json()["proposal_count"] >= 3


def test_ownership_and_records_survive_app_restart(client, app):
    task = create_challenge(client).json()
    another_application = api.create_app(app.state.database_path)
    with TestClient(another_application) as refreshed:
        refreshed.cookies.update(client.cookies)
        loaded = refreshed.get(f"/api/challenges/{task['id']}").json()
        assert loaded["is_owner"] and loaded["title"] == FIELDS["title"]
        assert len(refreshed.get("/api/bootstrap").json()["challenges"]) == 6


def test_foreign_origin_mutation_is_blocked(client):
    assert client.post("/api/challenges", headers={"origin": "https://unrelated.example"}, json={}).status_code == 403
    assert client.get("/api/not-real").status_code == 404


def test_concurrent_milestones_award_exactly_ten(app, client):
    task = create_challenge(client).json()
    proposal = propose(client, task["id"]).json()
    client.patch(f"/api/proposals/{proposal['id']}", json={"status": "accepted"})
    cookies = dict(client.cookies)

    def award(_):
        with TestClient(app) as browser:
            browser.cookies.update(cookies)
            return browser.post(f"/api/proposals/{proposal['id']}/milestones", json={
                "title": "Verified search", "evidence": "Ten search cases passed during a human-led review.",
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(award, range(2)))
    assert sorted(statuses) == [201, 409]
    refreshed = client.get(f"/api/challenges/{task['id']}").json()
    assert len(refreshed["progress"]) == 1 and refreshed["progress"][0]["points"] == 10


def test_trusted_analysis_cannot_be_reused_for_altered_fields(client, monkeypatch):
    review = [{"key": "context", "weight": 20, "level": 4, "points": 20}]
    monkeypatch.setattr(api, "analyze_brief", lambda *args, **kwargs: {
        "fields": FIELDS, "criteria": review, "mode": "ai", "questions": [],
    })
    result = client.post("/api/analyze", json={"draft": "Library search does not find the required textbooks.", "offline": True})
    assert result.status_code == 200
    identifier = result.json()["analysis_id"]
    original = create_challenge(client, analysis_id=identifier).json()
    assert original["score"] == 80 and original["score_source"] == "ai"
    assert original["analysis_fields_changed"] is False
    modified = create_challenge(client, analysis_id=identifier, fields={**FIELDS, "data": ""})
    assert modified.status_code == 201 and modified.json()["score"] == 25
    assert modified.json()["score_source"] == "local" and modified.json()["analysis_fields_changed"] is True
    unchanged = client.patch(f"/api/challenges/{original['id']}", json={"fields": {}, "confirmed": True}).json()
    assert unchanged["score_source"] == "ai" and unchanged["score"] == 80
    revised = client.patch(f"/api/challenges/{original['id']}", json={"fields": {"data": ""}, "confirmed": True}).json()
    assert revised["score_source"] == "local" and revised["analysis_fields_changed"] is True
    assert create_challenge(client, analysis_id="invented-id").status_code == 400


def test_missing_ai_is_a_clear_error_not_silent_canned_answer(client, monkeypatch):
    from agent.architect import AnalysisUnavailable

    def unavailable(*args, **kwargs):
        raise AnalysisUnavailable("AI is unavailable. Choose explicitly labelled offline mode to continue.")

    monkeypatch.setattr(api, "analyze_brief", unavailable)
    result = client.post("/api/analyze", json={"draft": "Library search fails for Kazakh textbooks."})
    assert result.status_code == 503
    assert "офлайн" in result.json()["detail"]
    english = client.post("/api/analyze", headers={"Accept-Language": "en"}, json={"draft": "Library search fails for Kazakh textbooks."})
    assert english.status_code == 503 and "offline" in english.json()["detail"]


@pytest.mark.parametrize("language,expected", [("ru", "автору"), ("kk-KZ,ru;q=0.5", "авторы"), ("en-US", "creator")])
def test_api_errors_follow_accept_language(client, language, expected):
    response = client.patch("/api/challenges/t1", headers={"Accept-Language": language}, json={
        "fields": {"title": "Cannot edit another person's task"}, "confirmed": True,
    })
    assert response.status_code == 403 and expected in response.json()["detail"]


def test_validation_is_russian_by_default_and_kazakh_on_request(client):
    response = client.post("/api/challenges", json={"confirmed": False})
    assert response.status_code == 422 and "Проверьте" in response.json()["detail"]
    result = client.post("/api/analyze", headers={"Accept-Language": "kk"}, json={"draft": "short"})
    assert result.status_code == 422 and "Кемінде 12" in result.json()["errors"][0]["message"]
    unsafe = client.post("/api/challenges/t1/proposals", json={
        "team_id": "team1", "idea": "A specific proposed solution", "plan": "Build and test a search prototype",
        "deadline": "10 days", "link": "javascript:alert(1)",
    })
    assert "полную ссылку" in unsafe.json()["detail"]


def test_analysis_and_publication_share_engine_field_limits(client):
    payload = {"draft": "Library students cannot find their textbooks.", "offline": True}
    assert client.post("/api/analyze", json={**payload, "answers": {"made_up_field": "answer"}}).status_code == 422
    assert client.post("/api/analyze", json={**payload, "answers": {"context": "a" * 4001}}).status_code == 422
    assert create_challenge(client, fields={**FIELDS, "data": "a" * 4001}).status_code == 422
    too_many = {key: "a" * 4000 for key in FIELDS if key != "title"}
    assert client.post("/api/analyze", json={**payload, "answers": too_many}).status_code == 422


def test_analysis_minute_ceiling_retries_and_offline_remains_available(app, client, monkeypatch):
    from server.limits import AnalysisLimits
    app.state.analysis_limits = AnalysisLimits(per_minute=2)
    monkeypatch.setattr(api, "analyze_brief", lambda *args, **kwargs: {"mode": "offline" if kwargs["offline"] else "ai"})
    payload = {"draft": "Library students cannot find their textbooks."}
    assert client.post("/api/analyze", json=payload).status_code == 200
    assert client.post("/api/analyze", json=payload).status_code == 200
    limited = client.post("/api/analyze", json=payload)
    assert limited.status_code == 429 and 1 <= int(limited.headers["Retry-After"]) <= 60
    assert "Подождите минуту" in limited.json()["detail"]
    assert client.post("/api/analyze", json={**payload, "offline": True}).status_code == 200


def test_duplicate_paid_analysis_is_blocked_then_guard_releases(app, client, monkeypatch):
    started, finish = Event(), Event()

    def slow_analysis(*args, **kwargs):
        started.set()
        assert finish.wait(10)
        return {"mode": "ai"}

    monkeypatch.setattr(api, "analyze_brief", slow_analysis)
    client.get("/api/bootstrap")
    cookies = dict(client.cookies)
    payload = {"draft": "Library students cannot find their textbooks."}

    def request_analysis():
        with TestClient(app) as browser:
            browser.cookies.update(cookies)
            return browser.post("/api/analyze", json=payload)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request_analysis)
        try:
            assert started.wait(5)
            blocked = client.post("/api/analyze", json=payload)
            assert blocked.status_code == 429 and "уже выполняется" in blocked.json()["detail"]
        finally:
            finish.set()
        assert pending.result(timeout=5).status_code == 200
    assert client.post("/api/analyze", json=payload).status_code == 200


def test_curated_seed_ratings_match_evidence_and_varied_expected_scores(tmp_path):
    from agent.architect import score_card_fields
    from agent.architect_tools import source_for
    from server.database import initialize, seed_file, transaction, ROOT
    import json

    with (ROOT / "data" / "seed_reviews.json").open(encoding="utf-8") as handle:
        reviews = json.load(handle)
    expected = {}
    for task in seed_file("tasks.json"):
        for item in reviews[task["id"]]:
            assert item["evidence"] in source_for(task, item["key"])
        rating = score_card_fields(task, reviews[task["id"]])
        expected[task["id"]] = rating["score"]
    assert len(set(expected.values())) == 5
    assert min(expected.values()) < 40 and max(expected.values()) >= 90
    path = tmp_path / "actual-seeds.sqlite3"
    initialize(path, score_card_fields)
    with transaction(path) as db:
        actual = {row["id"]: row["score"] for row in db.execute("SELECT id,score FROM challenges")}
    assert actual == expected
