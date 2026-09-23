"""Local SQLite storage. Each request owns a short transaction."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
CARD_FIELDS = (
    "title", "context", "need", "users", "data", "constraints",
    "expected_result", "success_criteria", "contact", "interaction_format",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def seed_file(name: str) -> list[dict[str, Any]]:
    with (ROOT / "data" / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: Path, score_fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS challenges (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                draft TEXT NOT NULL, topic TEXT NOT NULL, fields_json TEXT NOT NULL,
                score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
                readiness TEXT NOT NULL, criteria_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, skills TEXT NOT NULL,
                interests TEXT NOT NULL, technologies TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                challenge_id TEXT NOT NULL REFERENCES challenges(id),
                team_id TEXT REFERENCES teams(id), team_name TEXT NOT NULL,
                skills TEXT NOT NULL, idea TEXT NOT NULL, plan TEXT NOT NULL,
                deadline TEXT NOT NULL, link TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted'
                    CHECK(status IN ('submitted','shortlisted','accepted','rejected')),
                points INTEGER NOT NULL DEFAULT 0 CHECK(points IN (0,10)),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS proposals_challenge ON proposals(challenge_id);
            CREATE TABLE IF NOT EXISTS milestones (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(id),
                title TEXT NOT NULL, evidence TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 10 CHECK(points = 10),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                analysis_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(challenges)")}
        if "score_source" not in columns:
            db.execute("ALTER TABLE challenges ADD COLUMN score_source TEXT NOT NULL DEFAULT 'local'")
            db.execute("UPDATE challenges SET score_source = 'sample' WHERE owner = 'seed'")
        if "analysis_fields_changed" not in columns:
            db.execute("ALTER TABLE challenges ADD COLUMN analysis_fields_changed INTEGER NOT NULL DEFAULT 0")
        timestamp = now()
        drafts = {item["demo_card_id"]: item["text"] for item in seed_file("drafts.json")}
        review_path = ROOT / "data" / "seed_reviews.json"
        if review_path.exists():
            with review_path.open(encoding="utf-8") as handle:
                seed_reviews = json.load(handle)
        else:
            seed_reviews = {}
        for task in seed_file("tasks.json"):
            if db.execute("SELECT 1 FROM challenges WHERE id = ?", (task["id"],)).fetchone():
                continue
            fields = {key: task.get(key, "") for key in CARD_FIELDS}
            rating = score_fields(fields, review=seed_reviews.get(task["id"]), language="ru")
            db.execute(
                """INSERT INTO challenges
                   (id,owner,title,draft,topic,fields_json,score,readiness,criteria_json,
                    created_at,updated_at,score_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task["id"], "seed", fields["title"], drafts.get(task["id"], task["context"]),
                 task["topic"], encode(fields), rating["score"], rating["readiness"],
                 encode(rating["criteria"]), timestamp, timestamp, "sample"),
            )
        for team in seed_file("teams.json"):
            db.execute("INSERT OR IGNORE INTO teams VALUES (?,?,?,?,?)", (
                team["id"], team["name"], team["skills"], team["interests"], team["technologies"],
            ))
        for proposal in seed_file("proposals.json"):
            team = db.execute("SELECT * FROM teams WHERE id = ?", (proposal["team_id"],)).fetchone()
            db.execute(
                """INSERT OR IGNORE INTO proposals
                   (id,challenge_id,team_id,team_name,skills,idea,plan,deadline,link,status,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (proposal["id"], proposal["task_id"], team["id"], team["name"], team["skills"],
                 proposal["idea"], proposal["plan"], proposal["deadline"], proposal["link"],
                 proposal["status"], timestamp),
            )


def proposal_view(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    milestone = db.execute("SELECT * FROM milestones WHERE proposal_id = ?", (row["id"],)).fetchone()
    result["milestone"] = dict(milestone) if milestone else None
    return result


def challenge_view(db: sqlite3.Connection, row: sqlite3.Row, actor: str) -> dict[str, Any]:
    result = dict(row)
    result["source"] = "sample" if row["owner"] == "seed" else "confirmed"
    result["analysis_fields_changed"] = bool(result["analysis_fields_changed"])
    result["is_owner"] = result.pop("owner") == actor
    result["fields"] = json.loads(result.pop("fields_json"))
    result["criteria"] = json.loads(result.pop("criteria_json"))
    result["proposals"] = [proposal_view(db, item) for item in db.execute(
        "SELECT * FROM proposals WHERE challenge_id = ? ORDER BY created_at DESC, id", (row["id"],)
    ).fetchall()]
    result["proposal_count"] = len(result["proposals"])
    result["progress"] = [
        {**proposal["milestone"], "team_name": proposal["team_name"], "team_id": proposal["team_id"]}
        for proposal in result["proposals"] if proposal["milestone"]
    ]
    return result
