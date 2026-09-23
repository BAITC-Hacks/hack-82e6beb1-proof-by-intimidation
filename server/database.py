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
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT,
                input_hash TEXT NOT NULL, input_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
                analysis_id TEXT REFERENCES analyses(id), error_json TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(owner, request_id)
            );
            CREATE INDEX IF NOT EXISTS challenges_ranking ON challenges(score DESC, created_at DESC, id);
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


def challenge_metadata(row: sqlite3.Row, actor: str) -> dict[str, Any]:
    # Public responses are explicit allowlists: future storage columns stay private.
    result = {key: row[key] for key in (
        "id", "title", "topic", "score", "readiness", "created_at", "updated_at",
        "version", "score_source",
    )}
    result["source"] = "sample" if row["owner"] == "seed" else "confirmed"
    result["analysis_fields_changed"] = bool(row["analysis_fields_changed"])
    result["is_owner"] = row["owner"] == actor
    return result


def catalog_view(db: sqlite3.Connection, actor: str) -> list[dict[str, Any]]:
    # One set-based query, with bounded display excerpts, regardless of proposal count.
    rows = db.execute("""
        SELECT c.id,c.owner,c.title,c.topic,c.score,c.readiness,c.created_at,c.updated_at,
               c.version,c.score_source,c.analysis_fields_changed,
               json_object('title',c.title,
                   'context',substr(json_extract(c.fields_json,'$.context'),1,500),
                   'need',substr(json_extract(c.fields_json,'$.need'),1,500),
                   'expected_result',substr(json_extract(c.fields_json,'$.expected_result'),1,500)) AS display_fields,
               coalesce(p.total,0) AS proposal_count
        FROM challenges c LEFT JOIN (
            SELECT challenge_id,count(*) AS total FROM proposals GROUP BY challenge_id
        ) p ON p.challenge_id=c.id
        ORDER BY c.score DESC,c.created_at DESC,c.id
    """)
    return [{**challenge_metadata(row, actor), "summary": True,
             "fields": json.loads(row["display_fields"]), "proposal_count": row["proposal_count"]}
            for row in rows]


def public_criteria(criteria: list[dict[str, Any]], fields: dict[str, str]) -> list[dict[str, Any]]:
    # AI rationale can mention a private source even when its rated fields are public.
    # Expose scores and only quotes verifiable against the confirmed card, never that prose.
    confirmed = "\n".join(fields.values())
    result = []
    for criterion in criteria:
        item = {key: criterion[key] for key in ("key", "label", "weight", "level", "points") if key in criterion}
        evidence = criterion.get("evidence", "")
        item["evidence"] = evidence if isinstance(evidence, str) and evidence in confirmed else ""
        item.update(reason="", next_step="")
        result.append(item)
    return result


def challenge_view(db: sqlite3.Connection, row: sqlite3.Row, actor: str) -> dict[str, Any]:
    result = challenge_metadata(row, actor)
    result["summary"] = False
    stored_fields = json.loads(row["fields_json"])
    result["fields"] = {key: stored_fields.get(key, "") for key in CARD_FIELDS}
    criteria = json.loads(row["criteria_json"])
    result["criteria"] = criteria if result["is_owner"] else public_criteria(criteria, result["fields"])
    result["proposal_count"] = db.execute(
        "SELECT count(*) FROM proposals WHERE challenge_id=?", (row["id"],)
    ).fetchone()[0]
    result["proposals"], result["progress"] = [], []
    if not result["is_owner"]:
        # Team ideas and human milestone evidence are sent to the business, not the catalog.
        return result
    result["draft"] = row["draft"]
    proposals = db.execute(
        "SELECT * FROM proposals WHERE challenge_id = ? ORDER BY created_at DESC, id", (row["id"],)
    ).fetchall()
    milestones = {item["proposal_id"]: dict(item) for item in db.execute(
        """SELECT m.* FROM milestones m JOIN proposals p ON p.id=m.proposal_id
           WHERE p.challenge_id=?""", (row["id"],)
    )}
    result["proposals"] = [{**dict(item), "milestone": milestones.get(item["id"])} for item in proposals]
    result["progress"] = [
        {**proposal["milestone"], "team_name": proposal["team_name"], "team_id": proposal["team_id"]}
        for proposal in result["proposals"] if proposal["milestone"]
    ]
    return result
