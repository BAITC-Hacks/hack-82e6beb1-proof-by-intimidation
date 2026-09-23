"""Exercise the case's whole API workflow in isolated SQLite, optionally with real AI.

Default: explicit offline analysis, no API credit. --live: two real analyses per
selected scenario. These are acceptance signals, not a guarantee of AI quality.
No browser or existing application database is modified. Outputs may contain
synthetic test briefs and should stay inside the ignored .qa directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from tempfile import mkdtemp
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Opt into credit-using AI calls; never silently falls back.")
    parser.add_argument("--case", action="append", help="Limit to a supplied scenario ID; repeatable.")
    parser.add_argument("--output", default=".qa/workflow-acceptance.json")
    args = parser.parse_args()
    source_paths = ["agent/architect.py", "agent/architect_tools.py", "agent/architect_prompts.py", "agent/evidence.py", "server/app.py", "server/database.py", "server/jobs.py"]
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_paths}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = json.loads((ROOT / "data/acceptance_cases.json").read_text(encoding="utf-8"))
    cases = [case for case in cases if not args.case or case["id"] in args.case]
    if not cases:
        parser.error("Unknown case ID.")
    qa = ROOT / ".qa"
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(qa.resolve()):
        parser.error("Write diagnostic output inside .qa/ only.")
    qa.mkdir(exist_ok=True)
    workspace = Path(mkdtemp(prefix="workflow-", dir=qa))
    db_path = workspace / "isolated.sqlite3"
    os.environ["CHALLENGE_DB"] = str(db_path)
    from fastapi.testclient import TestClient
    from agent.architect_tools import verify_quotes
    api = importlib.import_module("server.app")
    application = api.create_app(db_path)
    records = []

    def check(record, name, passed, **evidence):
        record["checks"].append({"name": name, "passed": bool(passed), **evidence})

    def analyze(client, record, case, answers):
        started = time.perf_counter()
        request_id = str(uuid4())
        payload = {"draft": case["draft"], "answers": answers, "language": case["language"], "offline": not args.live, "request_id": request_id}
        created = client.post("/api/analysis-jobs", json=payload)
        check(record, "analysis_job_created", created.status_code == 202, status=created.status_code)
        if created.status_code != 202:
            raise RuntimeError("Analysis job creation failed: " + str(created.json().get("detail", created.status_code)))
        job = created.json()
        repeated = client.post("/api/analysis-jobs", json=payload)
        check(record, "analysis_retry_reuses_job", repeated.status_code in (200, 202) and repeated.json().get("job_id") == job["job_id"])
        # The client session is independent from other actors; no browser state is used.
        deadline = time.monotonic() + 240
        while job["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.2)
            response = client.get(f"/api/analysis-jobs/{job['job_id']}")
            if response.status_code != 200:
                raise RuntimeError("Could not retrieve analysis job.")
            job = response.json()
        elapsed = round(time.perf_counter() - started, 3)
        check(record, "analysis_job_succeeded", job["status"] == "succeeded", seconds=elapsed)
        if job["status"] != "succeeded":
            raise RuntimeError(str(job.get("error") or "Analysis job did not complete before the acceptance deadline."))
        result = job["analysis"]
        sources = {"draft": case["draft"], **{f"answers.{key}": value for key, value in answers.items()}}
        check(record, "honest_analysis_mode", result["mode"] == ("ai" if args.live else "offline"))
        check(record, "three_distinct_questions", len({item["field"] for item in result["questions"]}) >= 3)
        check(record, "grounded_evidence", verify_quotes(result["evidence"], sources)["valid"])
        check(record, "ten_editable_card_fields", set(result["fields"]) == set(api.CARD_FIELDS))
        check(record, "score_arithmetic", sum(item["points"] for item in result["criteria"]) == result["score"] and 0 <= result["score"] <= 100)
        if args.live and not answers:
            check(record, "critical_draft_facts_in_relevant_fields", all(all(term.casefold() in result["fields"].get(field, "").casefold() for term in terms) for field, terms in case.get("initial_field_terms", {}).items()))
        if answers:
            check(record, "all_explicit_answers_preserved", all(result["fields"].get(key) == value for key, value in answers.items()))
            check(record, "critical_final_facts_preserved", all(all(term.casefold() in result["fields"].get(field, "").casefold() for term in terms) for field, terms in case["field_terms"].items()))
        record["analyses"].append({"job_id": job["job_id"], "seconds": elapsed, "result": result})
        return result

    with TestClient(application) as owner:
        for case in cases:
            record = {"case": case["id"], "language": case["language"], "checks": [], "analyses": [], "manual_review_required": case["review_checks"]}
            records.append(record)
            try:
                first = analyze(owner, record, case, {})
                final = analyze(owner, record, case, case["answers"])
                check(record, "useful_answers_improve_readiness", final["score"] > first["score"], before=first["score"], after=final["score"])
                payload = {"draft": case["draft"], "fields": final["fields"], "topic": case["topic"], "analysis_id": final["analysis_id"], "language": case["language"]}
                check(record, "human_confirmation_required", owner.post("/api/challenges", json={**payload, "confirmed": False}).status_code == 422)
                publication = owner.post("/api/challenges", json={**payload, "confirmed": True})
                check(record, "publication_succeeded", publication.status_code == 201)
                if publication.status_code != 201:
                    raise RuntimeError("Publication failed after successful analysis.")
                task = publication.json()
                record["challenge_id"] = task["id"]
                check(record, "confirmed_rating_matches_analysis", task["score"] == final["score"])
                # Separate cookie jars: each visitor can propose, only the owner decides.
                proposals = []
                for number in range(3):
                    # The owner context already runs this app's lifespan. A new
                    # cookie jar must not restart its background job workers.
                    team = TestClient(application)
                    try:
                        detail = team.get(f"/api/challenges/{task['id']}").json()
                        check(record, f"visitor_{number}_no_private_draft", "draft" not in detail and "owner" not in detail)
                        check(record, f"visitor_{number}_cannot_read_analysis", team.get(f"/api/analysis-jobs/{record['analyses'][-1]['job_id']}").status_code in (403, 404))
                        reply = team.post(f"/api/challenges/{task['id']}/proposals", json={
                            "team_name": f"Synthetic acceptance team {case['id']} {number}", "skills": "Research, documentation, data validation",
                            "idea": "Review the supplied fictional materials and deliver the bounded result in this task.",
                            "plan": "Agree the acceptance checklist with the owner, prepare the artifact, and test each supplied example.",
                            "deadline": "Within the agreed case deadline", "link": "https://example.org/synthetic-prototype",
                        })
                        check(record, f"visitor_{number}_can_propose", reply.status_code == 201)
                        proposal = reply.json()
                        proposals.append(proposal)
                        check(record, f"visitor_{number}_cannot_self_select", team.patch(f"/api/proposals/{proposal['id']}", json={"status": "accepted"}).status_code == 403)
                    finally:
                        team.close()
                milestone = {"title": "Synthetic acceptance review", "evidence": "The owner reviewed the fictional deliverable against the supplied acceptance checklist. This is platform test data, not completed student work."}
                check(record, "unselected_team_cannot_earn_points", owner.post(f"/api/proposals/{proposals[0]['id']}/milestones", json=milestone).status_code == 409)
                for number, proposal in enumerate(proposals):
                    desired = "accepted" if number < 2 else "rejected"
                    decision = owner.patch(f"/api/proposals/{proposal['id']}", json={"status": desired})
                    check(record, f"manual_decision_{number}", decision.status_code == 200 and decision.json()["status"] == desired)
                awarded = owner.post(f"/api/proposals/{proposals[0]['id']}/milestones", json=milestone)
                check(record, "confirmed_progress_awards_ten", awarded.status_code == 201 and awarded.json()["points"] == 10)
                check(record, "duplicate_award_blocked", owner.post(f"/api/proposals/{proposals[0]['id']}/milestones", json=milestone).status_code == 409)
                refreshed = owner.get(f"/api/challenges/{task['id']}").json()
                check(record, "multiple_selected_teams_persist", sum(item["status"] == "accepted" for item in refreshed["proposals"]) == 2)
                catalog = owner.get("/api/bootstrap").json()["challenges"]
                check(record, "catalog_sorted_by_readiness", [item["score"] for item in catalog] == sorted((item["score"] for item in catalog), reverse=True))
                check(record, "publication_visible_in_catalog", any(item["id"] == task["id"] for item in catalog))
                record["owner_cookie"] = dict(owner.cookies)
            except Exception as error:
                # API errors are already sanitized; never print provider payloads.
                record["error"] = str(error)[:500]
                check(record, "workflow_completed", False)
            else:
                check(record, "workflow_completed", True)
            print(json.dumps({"case": case["id"], "checks": len(record["checks"]), "failed": [item["name"] for item in record["checks"] if not item["passed"]]}, ensure_ascii=False), flush=True)

    # Restart a separate app against ONLY the isolated database and prove persistence.
    with TestClient(api.create_app(db_path)) as restarted:
        for record in records:
            cookies = record.pop("owner_cookie", None)
            if not cookies:
                continue
            restarted.cookies.clear()
            restarted.cookies.update(cookies)
            saved = restarted.get(f"/api/challenges/{record['challenge_id']}").json()
            check(record, "restart_preserves_task_proposals_and_points", saved.get("proposal_count") == 3 and sum(item["points"] for item in saved.get("proposals", [])) == 10)
    count = sum(len(record["checks"]) for record in records)
    failed = sum(not item["passed"] for record in records for item in record["checks"])
    report = {"live_ai": args.live, "cases": len(records), "checks": count, "failed": failed,
              "source_sha256": source_hashes,
              "source_unchanged": all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in source_hashes.items()),
              "note": "Synthetic isolated API acceptance, not browser coverage, penetration testing, or a statistical AI quality estimate.", "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(records), "checks": count, "failed": failed, "live_ai": args.live, "report": str(output)}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
