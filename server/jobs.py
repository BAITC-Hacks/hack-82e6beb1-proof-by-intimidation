"""Small durable job ledger with a bounded, single-process worker queue.

SQLite retains outcomes, not a claim that work survives a process crash. Startup
explicitly fails interrupted jobs so the browser can recover and request a retry.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager, nullcontext
from pathlib import Path
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException

from server.database import encode, now, transaction
from server.messages import analysis_failure, translate

logger = logging.getLogger(__name__)
RESTARTED = "The server restarted before analysis finished. Your draft is safe; retry the analysis."
UNAVAILABLE = "AI is unavailable. Your text is preserved; retry later or choose the labelled offline check."


def job_view(db: Any, row: Any, language: str) -> dict[str, Any]:
    result = {"job_id": row["id"], "status": row["status"]}
    if row["status"] == "succeeded":
        analysis = db.execute("SELECT analysis_json FROM analyses WHERE id=? AND owner=?",
                              (row["analysis_id"], row["owner"])).fetchone()
        if analysis:
            result["analysis"] = json.loads(analysis["analysis_json"])
    elif row["status"] == "failed":
        error = json.loads(row["error_json"] or "{}")
        result["error"] = {"code": error.get("code", "analysis_unavailable"),
                           "detail": translate(error.get("message", UNAVAILABLE), language)}
        if error.get("diagnostic_id"):
            result["error"]["diagnostic_id"] = error["diagnostic_id"]
        if error.get("stage"):
            result["error"]["stage"] = error["stage"]
    return result


class AnalysisJobs:
    def __init__(self, path: Path, analyze: Callable[..., dict[str, Any]], limits: Callable[[], Any],
                 workers: int = 2, capacity: int = 8):
        self.path, self.analyze, self.limits = path, analyze, limits
        self.queue: Queue = Queue(maxsize=capacity)
        self.capacity = BoundedSemaphore(capacity)
        self.execution = BoundedSemaphore(workers)
        self.lock, self.stopped = Lock(), Event()
        self.threads = [Thread(target=self._worker, daemon=True, name=f"analysis-worker-{index}")
                        for index in range(workers)]

    def start(self) -> None:
        with transaction(self.path) as db:
            db.execute("""UPDATE analysis_jobs SET status='failed',error_json=?,updated_at=?
                          WHERE status IN ('queued','running')""",
                       (encode({"code": "server_restarted", "message": RESTARTED}), now()))
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.stopped.set()
        # Shutdown does not wait on an external provider. The interrupted ledger is
        # made explicit immediately; late worker results cannot change terminal jobs.
        with transaction(self.path) as db:
            db.execute("""UPDATE analysis_jobs SET status='failed',error_json=?,updated_at=?
                          WHERE status IN ('queued','running')""",
                       (encode({"code": "server_restarted", "message": RESTARTED}), now()))
        while True:
            try:
                _, _, lease = self.queue.get_nowait()
            except Empty:
                break
            lease.__exit__(None, None, None)
            self.capacity.release()
            self.queue.task_done()

    def submit(self, actor: str, payload: dict[str, Any], request_id: str | None, language: str) -> dict[str, Any]:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.lock:
            with transaction(self.path) as db:
                if request_id:
                    existing = db.execute("SELECT * FROM analysis_jobs WHERE owner=? AND request_id=?",
                                          (actor, request_id)).fetchone()
                    if existing:
                        if existing["input_hash"] != fingerprint:
                            raise HTTPException(409, "This analysis request was already used for a different draft. Start a new analysis.")
                        return job_view(db, existing, language)
            if self.stopped.is_set() or not self.capacity.acquire(blocking=False):
                raise HTTPException(429, "All analysis slots are busy. Please try again shortly.", headers={"Retry-After": "5"})
            lease = nullcontext() if payload["offline"] else self.limits().slot(actor)
            entered = False
            try:
                lease.__enter__()
                entered = True
                identifier, timestamp = str(uuid4()), now()
                with transaction(self.path) as db:
                    db.execute("""INSERT INTO analysis_jobs
                        (id,owner,request_id,input_hash,input_json,status,created_at,updated_at)
                        VALUES (?,?,?,?,?,'queued',?,?)""",
                               (identifier, actor, request_id, fingerprint, canonical, timestamp, timestamp))
                self.queue.put_nowait((identifier, actor, lease))
                return {"job_id": identifier, "status": "queued"}
            except BaseException:
                if entered:
                    lease.__exit__(None, None, None)
                self.capacity.release()
                raise

    def get(self, identifier: str, actor: str, language: str) -> dict[str, Any]:
        with transaction(self.path) as db:
            row = db.execute("SELECT * FROM analysis_jobs WHERE id=? AND owner=?", (identifier, actor)).fetchone()
            if row is None:
                raise HTTPException(404, "This analysis job is not available in this browser.")
            return job_view(db, row, language)

    @contextmanager
    def synchronous_slot(self, actor: str, offline: bool):
        """Legacy /analyze shares the global ceiling; it cannot bypass job limits."""
        if self.stopped.is_set() or not self.capacity.acquire(blocking=False):
            raise HTTPException(429, "All analysis slots are busy. Please try again shortly.", headers={"Retry-After": "5"})
        acquired = False
        try:
            acquired = self.execution.acquire(blocking=False)
            if not acquired:
                raise HTTPException(429, "All analysis slots are busy. Please try again shortly.", headers={"Retry-After": "5"})
            with nullcontext() if offline else self.limits().slot(actor):
                yield
        finally:
            if acquired:
                self.execution.release()
            self.capacity.release()

    def _worker(self) -> None:
        while not self.stopped.is_set():
            try:
                identifier, actor, lease = self.queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                with self.execution:
                    self._run(identifier, actor)
            except Exception:
                # Never log exception text, provider bodies, prompts, answers or keys.
                logger.error("analysis_job_storage_failure job_id=%s", identifier)
            finally:
                lease.__exit__(None, None, None)
                self.capacity.release()
                self.queue.task_done()

    def _run(self, identifier: str, actor: str) -> None:
        with transaction(self.path) as db:
            changed = db.execute("UPDATE analysis_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",
                                 (now(), identifier))
            if changed.rowcount != 1:
                return
            payload = json.loads(db.execute("SELECT input_json FROM analysis_jobs WHERE id=?", (identifier,)).fetchone()[0])
        try:
            result = self.analyze(payload["draft"], payload["answers"], payload["language"], offline=payload["offline"])
            analysis_id = str(uuid4())
            result = {**result, "analysis_id": analysis_id}
            with transaction(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                status = db.execute("SELECT status FROM analysis_jobs WHERE id=?", (identifier,)).fetchone()[0]
                if status != "running":
                    return
                db.execute("INSERT INTO analyses VALUES (?,?,?,?)", (analysis_id, actor, encode(result), now()))
                db.execute("UPDATE analysis_jobs SET status='succeeded',analysis_id=?,updated_at=? WHERE id=?",
                           (analysis_id, now(), identifier))
        except Exception as error:
            from agent.architect import AnalysisUnavailable
            # Provider/validation text is untrusted. Only stable codes and an opaque
            # diagnostic identifier are retained; user text never enters server logs.
            safe_code = getattr(error, "code", "analysis_unavailable")
            if safe_code not in {"not_configured", "provider_unavailable", "validation_failed", "analysis_unavailable"}:
                safe_code = "analysis_unavailable"
            message = analysis_failure("", "en", safe_code) if isinstance(error, AnalysisUnavailable) else UNAVAILABLE
            diagnostic = getattr(error, "diagnostic_id", None)
            if not isinstance(diagnostic, str) or not diagnostic.isalnum() or len(diagnostic) > 64:
                diagnostic = uuid4().hex[:12]
            detail = {"code": safe_code, "message": message, "diagnostic_id": diagnostic}
            stage = getattr(error, "stage", None)
            if stage in {"agent", "audit", "repair"}:
                detail["stage"] = stage
            with transaction(self.path) as db:
                db.execute("UPDATE analysis_jobs SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                           (encode(detail), now(), identifier))
            logger.warning("analysis_job_failed job_id=%s code=%s diagnostic_id=%s", identifier, safe_code, diagnostic)
