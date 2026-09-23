"""Public API acceptance tests: isolated databases; never call an external AI service."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

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


@pytest.mark.parametrize("link", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.com", "not a url",
                                  "https://example.com:not-a-port/prototype", "https://example.com:99999/", "https://example.com:0/",
                                  "https://example.com/proto\u0000type"])
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


def test_private_draft_review_and_proposals_never_enter_public_views(app, client, monkeypatch):
    marker = "PRIVATE-NOTE-123"
    review = [{"key": "context", "weight": 20, "level": 4, "points": 20,
               "evidence": marker, "reason": marker, "next_step": marker}]
    monkeypatch.setattr(api, "analyze_brief", lambda *args, **kwargs: {
        "fields": FIELDS, "criteria": review, "mode": "ai", "trace": [{"private": marker}],
    })
    analysis = client.post("/api/analyze", json={"draft": "Library task " + marker, "offline": True}).json()
    task = create_challenge(client, draft="Library task " + marker, analysis_id=analysis["analysis_id"]).json()
    propose(client, task["id"], idea="Our private team proposal " + marker)
    assert marker in client.get(f"/api/challenges/{task['id']}").text
    # Even the creator's bootstrap never includes private payloads.
    assert marker not in client.get("/api/bootstrap").text
    with TestClient(app) as visitor:
        detail = visitor.get(f"/api/challenges/{task['id']}")
        assert detail.status_code == 200 and marker not in detail.text
        assert "draft" not in detail.json() and detail.json()["proposals"] == []
        assert detail.json()["proposal_count"] == 1
        assert marker not in visitor.get("/api/bootstrap").text


def test_partial_edit_validates_merged_card_total(client):
    fields = {key: "a" * 2600 for key in FIELDS}
    fields["title"] = "Long but valid task"
    task = create_challenge(client, fields=fields).json()
    result = client.patch(f"/api/challenges/{task['id']}", json={
        "fields": {"context": "b" * 4000}, "confirmed": True, "version": 1,
    })
    assert result.status_code == 422 and "24 000" in result.json()["detail"]
    assert client.get(f"/api/challenges/{task['id']}").json()["version"] == 1


def test_summary_payload_is_bounded_and_stats_do_not_require_proposal_bodies(client):
    task = create_challenge(client, fields={**FIELDS, "context": "a" * 4000}).json()
    for _ in range(12):
        assert propose(client, task["id"], idea="Large proposal " + "z" * 5900).status_code == 201
    response = client.get("/api/bootstrap").json()
    summary = next(item for item in response["challenges"] if item["id"] == task["id"])
    assert summary["summary"] and summary["proposal_count"] == 12
    assert len(summary["fields"]["context"]) == 500
    assert not {"draft", "criteria", "proposals", "progress"}.intersection(summary)
    assert response["stats"]["proposals"] == 17


def job_payload(**overrides):
    return {"draft": "Students cannot find Kazakh library textbooks.", "answers": {},
            "language": "en", "offline": False, "request_id": str(uuid4()), **overrides}


def await_job(client, identifier, timeout=5):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = client.get(f"/api/analysis-jobs/{identifier}")
        assert result.status_code == 200
        body = result.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        sleep(0.01)
    raise AssertionError("Background analysis did not finish within the test deadline")


def test_analysis_job_survives_refresh_is_private_and_idempotent(app, client, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "analyze_brief", lambda *args, **kwargs: calls.append(args) or {
        "fields": FIELDS, "criteria": [{"key": "context", "weight": 20, "level": 4, "points": 20}], "mode": "ai",
    })
    payload = job_payload()
    created = client.post("/api/analysis-jobs", json=payload)
    assert created.status_code == 202
    identifier = created.json()["job_id"]
    completed = await_job(client, identifier)
    assert completed["status"] == "succeeded"
    assert completed["analysis"]["analysis_id"]
    assert len(calls) == 1
    recovered = client.post("/api/analysis-jobs", json=payload)
    assert recovered.status_code == 202 and recovered.json() == completed
    assert len(calls) == 1
    with TestClient(app) as visitor:
        assert visitor.get(f"/api/analysis-jobs/{identifier}").status_code == 404
    with TestClient(app) as refreshed:
        refreshed.cookies.update(client.cookies)
        assert refreshed.get(f"/api/analysis-jobs/{identifier}").json() == completed
    with TestClient(api.create_app(app.state.database_path)) as restarted:
        restarted.cookies.update(client.cookies)
        assert restarted.get(f"/api/analysis-jobs/{identifier}").json() == completed
    mismatch = client.post("/api/analysis-jobs", json={**payload, "draft": "A different business problem requires attention."})
    assert mismatch.status_code == 409
    published = create_challenge(client, analysis_id=completed["analysis"]["analysis_id"])
    assert published.status_code == 201 and published.json()["score_source"] == "ai"


def test_job_errors_are_sanitized_and_explicit_retry_uses_new_id(client, monkeypatch):
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("SECRET-USER-PAYLOAD provider headers Authorization xyz")

    monkeypatch.setattr(api, "analyze_brief", broken)
    payload = job_payload()
    result = client.post("/api/analysis-jobs", json=payload).json()
    failed = await_job(client, result["job_id"])
    assert failed["status"] == "failed" and failed["error"]["diagnostic_id"]
    assert "SECRET" not in str(failed) and "офлайн" in failed["error"]["detail"]
    assert client.post("/api/analysis-jobs", json=payload).json() == failed
    assert len(calls) == 1
    retried = client.post("/api/analysis-jobs", json={**payload, "request_id": str(uuid4())}).json()
    assert retried["job_id"] != failed["job_id"]
    assert await_job(client, retried["job_id"])["status"] == "failed" and len(calls) == 2


def test_jobs_share_actor_limit_with_sync_analysis_and_retry_is_safe(app, client, monkeypatch):
    started, finish = Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return {"mode": "ai", "fields": FIELDS}

    monkeypatch.setattr(api, "analyze_brief", slow)
    payload = job_payload()
    queued = client.post("/api/analysis-jobs", json=payload).json()
    try:
        assert started.wait(2)
        repeat = client.post("/api/analysis-jobs", json=payload)
        assert repeat.status_code == 202 and repeat.json()["job_id"] == queued["job_id"]
        second = client.post("/api/analysis-jobs", json={**payload, "request_id": str(uuid4())})
        assert second.status_code == 429 and int(second.headers["Retry-After"]) > 0
        sync = client.post("/api/analyze", json={key: value for key, value in payload.items() if key != "request_id"})
        assert sync.status_code == 429
    finally:
        finish.set()
    assert await_job(client, queued["job_id"])["status"] == "succeeded"


def test_jobs_have_bounded_global_concurrency_and_capacity(app, client, monkeypatch):
    from threading import Lock
    finish, lock = Event(), Lock()
    active = [0, 0]

    def slow(*args, **kwargs):
        with lock:
            active[0] += 1
            active[1] = max(active)
        try:
            assert finish.wait(5)
            return {"mode": "offline", "fields": FIELDS}
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(api, "analyze_brief", slow)
    identifiers = []
    try:
        for _ in range(8):
            response = client.post("/api/analysis-jobs", json=job_payload(offline=True))
            assert response.status_code == 202
            identifiers.append(response.json()["job_id"])
        full = client.post("/api/analysis-jobs", json=job_payload(offline=True))
        assert full.status_code == 429 and "Retry-After" in full.headers
        assert active[1] <= 2
    finally:
        finish.set()
    assert all(await_job(client, identifier)["status"] == "succeeded" for identifier in identifiers)


def test_restart_marks_abandoned_jobs_failed_and_preserves_completed(tmp_path, monkeypatch):
    import hashlib
    from server.database import encode, initialize, now, transaction
    path = tmp_path / "restart-jobs.sqlite3"
    monkeypatch.setattr(api, "score_card_fields", fake_score)
    initialize(path, fake_score)
    token = "a" * 64
    owner = hashlib.sha256(token.encode()).hexdigest()
    identifiers = [str(uuid4()), str(uuid4())]
    with transaction(path) as db:
        for identifier, status in zip(identifiers, ["queued", "running"]):
            db.execute("""INSERT INTO analysis_jobs
                (id,owner,request_id,input_hash,input_json,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (identifier, owner, identifier, "hash", encode(job_payload()), status, now(), now()))
    with TestClient(api.create_app(path)) as browser:
        browser.cookies.set(api.COOKIE, token)
        for identifier in identifiers:
            result = browser.get(f"/api/analysis-jobs/{identifier}").json()
            assert result["status"] == "failed" and result["error"]["code"] == "server_restarted"
            assert "перезапущен" in result["error"]["detail"]


def test_owner_can_reject_all_teams_without_assignment(client):
    task = create_challenge(client).json()
    proposals = [propose(client, task["id"], team_id=f"team{index}").json() for index in (1, 2, 3)]
    for proposal in proposals:
        assert proposal["status"] == "submitted"
        assert client.patch(f"/api/proposals/{proposal['id']}", json={"status": "rejected"}).status_code == 200
    detail = client.get(f"/api/challenges/{task['id']}").json()
    assert all(item["status"] == "rejected" and item["points"] == 0 for item in detail["proposals"])
    assert detail["progress"] == []


@pytest.mark.parametrize("language,draft", [
    ("ru", "Студенты не находят учебники на казахском языке в каталоге библиотеки."),
    ("kk", "Студенттер кітапхана каталогынан қазақ тіліндегі оқулықтарды таба алмайды."),
    ("en", "Students cannot find Kazakh textbooks in the library catalog."),
])
def test_real_offline_three_complete_scenarios(tmp_path, language, draft):
    # Real domain engine, explicitly offline. No mock grades or provider calls.
    with TestClient(api.create_app(tmp_path / f"journey-{language}.sqlite3")) as browser:
        weak = browser.post("/api/analyze", json={"draft": draft, "language": language, "offline": True})
        assert weak.status_code == 200
        first = weak.json()
        assert first["mode"] == "offline" and len(first["questions"]) >= 3
        job = browser.post("/api/analysis-jobs", json=job_payload(draft=draft, language=language, answers=FIELDS, offline=True)).json()
        outcome = await_job(browser, job["job_id"])
        assert outcome["status"] == "succeeded"
        analysis = outcome["analysis"]
        assert first["score"] < analysis["score"] <= 27
        published = create_challenge(browser, draft=draft, language=language, fields=analysis["fields"], analysis_id=analysis["analysis_id"])
        assert published.status_code == 201
        task = published.json()
        assert task["score"] == analysis["score"] and task["score_source"] == "local"
        assert any(card["id"] == task["id"] for card in browser.get("/api/bootstrap").json()["challenges"])
        proposal = propose(browser, task["id"], team_id=None, team_name="Independent student team").json()
        assert proposal["status"] == "submitted"
        assert browser.patch(f"/api/proposals/{proposal['id']}", json={"status": "accepted"}).status_code == 200
        award = browser.post(f"/api/proposals/{proposal['id']}/milestones", json={
            "title": "Human-reviewed prototype", "evidence": "The business reviewed ten catalog search results in the shared prototype.",
        })
        assert award.status_code == 201 and award.json()["points"] == 10


def test_synchronous_analysis_cannot_bypass_global_job_limit(app, client, monkeypatch):
    from threading import Lock
    running, lock, finish = Event(), Lock(), Event()
    count = [0]

    def slow(*args, **kwargs):
        with lock:
            count[0] += 1
            if count[0] == 2:
                running.set()
        assert finish.wait(5)
        return {"mode": "offline"}

    monkeypatch.setattr(api, "analyze_brief", slow)
    jobs = [client.post("/api/analysis-jobs", json=job_payload(offline=True)).json() for _ in range(2)]
    try:
        assert running.wait(2)
        with TestClient(app) as different_browser:
            response = different_browser.post("/api/analyze", json={
                "draft": "Another browser cannot bypass the shared concurrency ceiling.", "offline": True,
            })
            assert response.status_code == 429 and response.headers["Retry-After"] == "5"
    finally:
        finish.set()
    assert all(await_job(client, job["job_id"])["status"] == "succeeded" for job in jobs)


def test_ai_error_codes_and_stage_are_preserved_safely(client, monkeypatch):
    from agent.architect import AnalysisUnavailable

    def invalid(*args, **kwargs):
        raise AnalysisUnavailable("Untrusted body SECRET", code="validation_failed", stage="audit")

    monkeypatch.setattr(api, "analyze_brief", invalid)
    job = client.post("/api/analysis-jobs", json=job_payload()).json()
    result = await_job(client, job["job_id"])
    assert result["error"]["code"] == "validation_failed" and result["error"]["stage"] == "audit"
    assert "проверку фактов" in result["error"]["detail"] and "SECRET" not in str(result)


def test_legacy_analysis_unexpected_failure_is_sanitized(client, monkeypatch):
    def unexpected(*args, **kwargs):
        raise RuntimeError("SECRET prompt and provider Authorization body")
    monkeypatch.setattr(api, "analyze_brief", unexpected)
    response = client.post("/api/analyze", json={"draft": "Library students cannot find the textbooks."})
    assert response.status_code == 503 and "SECRET" not in response.text
    assert "офлайн" in response.json()["detail"]
