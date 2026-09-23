"""FastAPI entrypoint: python -m uvicorn server.app:app --port 8000."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.database import (
    CARD_FIELDS, ROOT, challenge_view, encode, initialize, now,
    proposal_view, seed_file, transaction,
)
from server.limits import AnalysisLimits
from server.messages import analysis_failure, language_from_header, translate, validation_message

load_dotenv()
Language = Literal["ru", "kk", "en"]
COOKIE = "sana_workspace"
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def analyze_brief(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from agent.architect import analyze_brief as analyze
    return analyze(*args, **kwargs)


def score_card_fields(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from agent.architect import score_card_fields as score
    return score(*args, **kwargs)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def check_fields(value: dict[str, str]) -> dict[str, str]:
    if set(value) - set(CARD_FIELDS):
        raise ValueError("Unknown card field. Only the ten task-card fields are supported.")
    clean = {key: text.strip() for key, text in value.items()}
    if any(len(text) > 4000 for text in clean.values()) or sum(map(len, clean.values())) > 24000:
        raise ValueError("The card is too long. Limit each field to 4,000 characters and the card to 24,000.")
    if len(clean.get("title", "")) > 180:
        raise ValueError("Use a title of at most 180 characters.")
    return clean


class AnalyzeInput(Input):
    draft: str = Field(min_length=12, max_length=12000)
    answers: dict[str, str] = Field(default_factory=dict)
    language: Language = "ru"
    offline: bool = False

    @field_validator("draft")
    @classmethod
    def meaningful_draft(cls, value: str) -> str:
        if len(re.findall(r"[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]", value)) < 5:
            raise ValueError("Describe the task in words in English, Kazakh or Russian.")
        return value

    @field_validator("answers")
    @classmethod
    def bounded_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - set(CARD_FIELDS):
            raise ValueError("Unknown card field. Only the ten task-card fields are supported.")
        if any(len(text) > 4000 for text in value.values()):
            raise ValueError("Use at most 4,000 characters in each answer.")
        if sum(map(len, value.values())) > 24000:
            raise ValueError("The answers must total at most 24,000 characters.")
        return {key: text.strip() for key, text in value.items()}


class ChallengeInput(Input):
    draft: str = Field(min_length=8, max_length=12000)
    fields: dict[str, str]
    topic: str = Field(default="Образование", min_length=2, max_length=80)
    analysis_id: str | None = Field(default=None, max_length=80)
    confirmed: Literal[True]
    language: Language = "ru"

    _validate_fields = field_validator("fields")(check_fields)


class ChallengePatch(Input):
    fields: dict[str, str]
    draft: str | None = Field(default=None, min_length=8, max_length=12000)
    topic: str | None = Field(default=None, min_length=2, max_length=80)
    analysis_id: str | None = Field(default=None, max_length=80)
    confirmed: Literal[True]
    version: int | None = Field(default=None, ge=1)
    language: Language = "ru"

    _validate_fields = field_validator("fields")(check_fields)


class ProposalInput(Input):
    team_id: str | None = Field(default=None, max_length=80)
    team_name: str | None = Field(default=None, min_length=2, max_length=120)
    skills: str = Field(default="", max_length=1000)
    idea: str = Field(min_length=10, max_length=6000)
    plan: str = Field(min_length=10, max_length=6000)
    deadline: str = Field(min_length=2, max_length=200)
    link: str = Field(min_length=8, max_length=2000)

    @field_validator("link")
    @classmethod
    def safe_link(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            valid = valid and not parsed.username and not parsed.password
            valid = valid and not any(character.isspace() for character in value)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Provide a full http:// or https:// prototype link without credentials.")
        return value


class DecisionInput(Input):
    status: Literal["accepted", "rejected", "shortlisted", "submitted"]


class MilestoneInput(Input):
    title: str = Field(min_length=3, max_length=180)
    evidence: str = Field(min_length=10, max_length=6000)


def _challenge(db: sqlite3.Connection, challenge_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This task could not be found.")
    return row


def _owned(row: sqlite3.Row, actor: str) -> None:
    if row["owner"] != actor:
        raise HTTPException(403, "Only the task's creator can make this change from their original browser.")


def _confirmed_rating(
    db: sqlite3.Connection, actor: str, fields: dict[str, str], analysis_id: str | None, language: str,
) -> dict[str, Any]:
    review = None
    score_source, changed = "local", False
    if analysis_id:
        stored = db.execute("SELECT * FROM analyses WHERE id = ? AND owner = ?", (analysis_id, actor)).fetchone()
        if stored is None:
            raise HTTPException(400, "The analysis is not available in this workspace. Analyze the draft again.")
        analysis = json.loads(stored["analysis_json"])
        if fields == {key: str(analysis.get("fields", {}).get(key, "")).strip() for key in CARD_FIELDS}:
            review = analysis.get("criteria")
            if review and analysis.get("mode") == "ai":
                score_source = "ai"
        else:
            changed = True
    return {**score_card_fields(fields, review=review, language=language),
            "score_source": score_source, "analysis_fields_changed": changed}


def _complete_fields(fields: dict[str, str]) -> dict[str, str]:
    result = {key: fields.get(key, "") for key in CARD_FIELDS}
    if len(result["title"].strip()) < 3:
        raise HTTPException(422, "Give your task a title of at least three characters before publishing.")
    if not result["context"] and not result["need"]:
        raise HTTPException(422, "Describe the current situation or the business need before publishing.")
    return result


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = Path(database_path or os.getenv("CHALLENGE_DB", str(ROOT / "data" / "challenges.sqlite3")))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        initialize(path, score_card_fields)
        yield

    application = FastAPI(title="AI Sana Challenge Hub", version="2.0.0", lifespan=lifespan)
    application.state.database_path = path
    application.state.analysis_limits = AnalysisLimits()
    application.add_middleware(
        CORSMiddleware, allow_origins=sorted(DEV_ORIGINS), allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Accept-Language"],
        expose_headers=["Retry-After"],
    )

    @application.middleware("http")
    async def workspace(request: Request, call_next: Any):
        request.state.language = language_from_header(request.headers.get("accept-language", ""))
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            same_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin not in DEV_ORIGINS | {same_origin}:
                return JSONResponse({"detail": translate("This request must come from the Challenge Hub website.", request.state.language)}, status_code=403)
        token = request.cookies.get(COOKIE, "")
        fresh = re.fullmatch(r"[a-f0-9]{64}", token) is None
        if fresh:
            token = secrets.token_hex(32)
        request.state.actor = hashlib.sha256(token.encode()).hexdigest()
        response = await call_next(request)
        if fresh:
            response.set_cookie(
                COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                max_age=60 * 60 * 24 * 30, path="/",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        language = request.state.language
        errors = [{"field": ".".join(map(str, item["loc"][1:])), "message": validation_message(item, language)} for item in error.errors()]
        detail = translate("Please check the highlighted information and try again.", language)
        if errors:
            detail += " " + errors[0]["message"]
        return JSONResponse({"detail": detail, "errors": errors}, status_code=422)

    @application.exception_handler(StarletteHTTPException)
    async def friendly_error(request: Request, error: StarletteHTTPException):
        detail = translate(error.detail, request.state.language) if isinstance(error.detail, str) else error.detail
        return JSONResponse({"detail": detail}, status_code=error.status_code, headers=error.headers)

    @application.exception_handler(sqlite3.OperationalError)
    async def storage_error(request: Request, error: sqlite3.OperationalError):
        return JSONResponse({"detail": translate("Storage is temporarily busy. Your change was not saved; please try again.", request.state.language)}, status_code=503)

    @application.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request: Request, error: sqlite3.IntegrityError):
        return JSONResponse({"detail": translate("This change conflicts with an existing record. Refresh and try again.", request.state.language)}, status_code=409)

    @application.get("/api/health")
    def health():
        with transaction(path) as db:
            db.execute("SELECT 1")
        return {"status": "ok", "version": "2.0.0"}

    @application.get("/api/bootstrap")
    def bootstrap(request: Request):
        with transaction(path) as db:
            challenges = [challenge_view(db, row, request.state.actor) for row in db.execute(
                "SELECT * FROM challenges ORDER BY score DESC, created_at DESC, id"
            ).fetchall()]
            teams = [dict(row) for row in db.execute("SELECT * FROM teams ORDER BY id")]
            cards = {task["id"]: task for task in seed_file("tasks.json")}
            drafts = [{
                "id": item["id"], "text": item["text"], "topic": item["topic"],
                "answers": {key: cards[item["demo_card_id"]].get(key, "") for key in CARD_FIELDS},
            } for item in seed_file("drafts.json")]
            proposals = [p for task in challenges for p in task["proposals"]]
            return {
                "challenges": challenges, "teams": teams, "drafts": drafts,
                "ai": {
                    "available": bool(os.getenv("OPENAI_API_KEY", "").strip() and os.getenv("OPENAI_MODEL", "").strip()),
                    "model": os.getenv("OPENAI_MODEL", ""),
                },
                "stats": {
                    "challenges": len(challenges), "teams": len(teams), "proposals": len(proposals),
                    "ready": sum(task["score"] >= 70 for task in challenges),
                    "my_challenges": sum(task["is_owner"] for task in challenges),
                    "accepted": sum(p["status"] == "accepted" for p in proposals),
                    "completed": sum(bool(p["milestone"]) for p in proposals),
                },
            }

    @application.post("/api/analyze")
    def analyze(payload: AnalyzeInput, request: Request):
        from agent.architect import AnalysisUnavailable
        try:
            with nullcontext() if payload.offline else application.state.analysis_limits.slot(request.state.actor):
                result = analyze_brief(payload.draft, payload.answers, payload.language, offline=payload.offline)
        except AnalysisUnavailable as error:
            raise HTTPException(503, analysis_failure(str(error), request.state.language)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        identifier = str(uuid4())
        result = {**result, "analysis_id": identifier}
        with transaction(path) as db:
            db.execute("INSERT INTO analyses VALUES (?,?,?,?)", (
                identifier, request.state.actor, encode(result), now(),
            ))
        return result

    @application.post("/api/challenges", status_code=201)
    def publish(payload: ChallengeInput, request: Request):
        fields = _complete_fields(payload.fields)
        identifier, timestamp = str(uuid4()), now()
        with transaction(path) as db:
            rating = _confirmed_rating(db, request.state.actor, fields, payload.analysis_id, payload.language)
            db.execute(
                """INSERT INTO challenges
                   (id,owner,title,draft,topic,fields_json,score,readiness,criteria_json,created_at,updated_at,
                    score_source,analysis_fields_changed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (identifier, request.state.actor, fields["title"], payload.draft, payload.topic,
                 encode(fields), rating["score"], rating["readiness"], encode(rating["criteria"]), timestamp, timestamp,
                 rating["score_source"], int(rating["analysis_fields_changed"])),
            )
            return challenge_view(db, _challenge(db, identifier), request.state.actor)

    @application.get("/api/challenges/{challenge_id}")
    def get_challenge(challenge_id: str, request: Request):
        with transaction(path) as db:
            return challenge_view(db, _challenge(db, challenge_id), request.state.actor)

    @application.patch("/api/challenges/{challenge_id}")
    def edit_challenge(challenge_id: str, payload: ChallengePatch, request: Request):
        with transaction(path) as db:
            row = _challenge(db, challenge_id)
            _owned(row, request.state.actor)
            if payload.version is not None and payload.version != row["version"]:
                raise HTTPException(409, "This task changed in another tab. Refresh before saving your edits.")
            fields = _complete_fields({**json.loads(row["fields_json"]), **payload.fields})
            rating = _confirmed_rating(db, request.state.actor, fields, payload.analysis_id, payload.language)
            if not payload.analysis_id:
                unchanged = fields == json.loads(row["fields_json"])
                if unchanged:
                    rating = {**score_card_fields(fields, review=json.loads(row["criteria_json"]), language=payload.language),
                              "score_source": row["score_source"], "analysis_fields_changed": bool(row["analysis_fields_changed"])}
                elif row["score_source"] == "ai" or row["analysis_fields_changed"]:
                    rating["analysis_fields_changed"] = True
            updated = db.execute(
                """UPDATE challenges SET title=?,draft=?,topic=?,fields_json=?,score=?,readiness=?,
                   criteria_json=?,updated_at=?,score_source=?,analysis_fields_changed=?,
                   version=version+1 WHERE id=? AND version=?""",
                (fields["title"], payload.draft if payload.draft is not None else row["draft"],
                 payload.topic if payload.topic is not None else row["topic"], encode(fields),
                 rating["score"], rating["readiness"], encode(rating["criteria"]), now(),
                 rating["score_source"], int(rating["analysis_fields_changed"]), challenge_id, row["version"]),
            )
            if updated.rowcount != 1:
                raise HTTPException(409, "This task changed while you were editing. Refresh and try again.")
            return challenge_view(db, _challenge(db, challenge_id), request.state.actor)

    @application.post("/api/challenges/{challenge_id}/proposals", status_code=201)
    def submit_proposal(challenge_id: str, payload: ProposalInput, request: Request):
        identifier = str(uuid4())
        with transaction(path) as db:
            _challenge(db, challenge_id)
            team = db.execute("SELECT * FROM teams WHERE id = ?", (payload.team_id,)).fetchone() if payload.team_id else None
            if payload.team_id and not team:
                raise HTTPException(422, "Choose an existing sample team or enter your own team's name.")
            if not team and not payload.team_name:
                raise HTTPException(422, "Enter your team's name before submitting a proposal.")
            db.execute(
                """INSERT INTO proposals
                   (id,challenge_id,team_id,team_name,skills,idea,plan,deadline,link,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (identifier, challenge_id, team["id"] if team else None,
                 team["name"] if team else payload.team_name, payload.skills or (team["skills"] if team else ""),
                 payload.idea, payload.plan, payload.deadline, payload.link, now()),
            )
            return proposal_view(db, db.execute("SELECT * FROM proposals WHERE id = ?", (identifier,)).fetchone())

    @application.patch("/api/proposals/{proposal_id}")
    def decide(proposal_id: str, payload: DecisionInput, request: Request):
        with transaction(path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "This proposal could not be found.")
            _owned(_challenge(db, row["challenge_id"]), request.state.actor)
            if row["points"] and payload.status != "accepted":
                raise HTTPException(409, "A team with confirmed progress remains accepted; its recorded work cannot be revoked here.")
            db.execute("UPDATE proposals SET status = ? WHERE id = ?", (payload.status, proposal_id))
            return proposal_view(db, db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone())

    @application.post("/api/proposals/{proposal_id}/milestones", status_code=201)
    def confirm_progress(proposal_id: str, payload: MilestoneInput, request: Request):
        with transaction(path) as db:
            # Reserve the writer before checking status, so concurrent confirmations cannot award twice.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "This proposal could not be found.")
            _owned(_challenge(db, row["challenge_id"]), request.state.actor)
            if row["status"] != "accepted":
                raise HTTPException(409, "Choose this team before confirming its completed milestone.")
            if row["points"] or db.execute("SELECT 1 FROM milestones WHERE proposal_id = ?", (proposal_id,)).fetchone():
                raise HTTPException(409, "Progress has already been confirmed for this proposal. Points are awarded once.")
            db.execute("INSERT INTO milestones VALUES (?,?,?,?,?,?)", (
                str(uuid4()), proposal_id, payload.title, payload.evidence, 10, now(),
            ))
            db.execute("UPDATE proposals SET points = 10 WHERE id = ?", (proposal_id,))
            return proposal_view(db, db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone())

    @application.get("/{spa_path:path}", include_in_schema=False)
    def frontend(spa_path: str):
        if spa_path == "api" or spa_path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint.")
        dist = (ROOT / "frontend" / "dist").resolve()
        candidate = (dist / spa_path).resolve()
        if not candidate.is_relative_to(dist):
            raise HTTPException(404, "Page not found.")
        if candidate.is_file():
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.is_file() and not Path(spa_path).suffix:
            return FileResponse(index)
        raise HTTPException(404, "Frontend is not built. Run npm install and npm run build in frontend/, or use the Vite development server.")

    return application


app = create_app()
