"""Bounded in-process catalog regression benchmark, not production capacity claims.

Run with pytest -s to see timings. Temporary SQLite only; no external API calls.
"""

from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from math import ceil
from statistics import median
from time import perf_counter

from fastapi.testclient import TestClient
import pytest

from server.database import encode, now, transaction

api = importlib.import_module("server.app")


@pytest.mark.parametrize("count", [5, 100, 1000])
def test_catalog_set_based_scaling(tmp_path, monkeypatch, count):
    application = api.create_app(tmp_path / f"catalog-{count}.sqlite3")
    with TestClient(application) as browser:
        with transaction(application.state.database_path) as db:
            seed = dict(db.execute("SELECT * FROM challenges WHERE id='t1'").fetchone())
            fields = json.loads(seed["fields_json"])
            fields["context"] = "Synthetic library context. " * 150
            fields["need"] = "Synthetic need. " * 100
            values = []
            for index in range(5, count):
                values.append((f"benchmark-{index}", "benchmark-owner", f"Synthetic task {index}",
                    "PRIVATE INPUT " * 700, "Education", encode(fields), index % 101, seed["readiness"],
                    seed["criteria_json"], now(), now()))
            db.executemany("""INSERT INTO challenges
                (id,owner,title,draft,topic,fields_json,score,readiness,criteria_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", values)
            db.executemany("""INSERT INTO proposals
                (id,challenge_id,team_id,team_name,skills,idea,plan,deadline,link,created_at)
                VALUES (?,?,'team1','Synthetic team','Python',?,?, '2 weeks','https://example.com',?)""",
                [(f"proposal-{index}-{number}", f"benchmark-{index}", "Private solution. " * 100,
                  "Private plan. " * 100, now()) for index in range(5, count) for number in range(3)])

        import server.database as database
        original_connect = database.sqlite3.connect
        statements = []

        def traced(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            connection.set_trace_callback(lambda sql: statements.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)
            return connection

        monkeypatch.setattr(database.sqlite3, "connect", traced)
        browser.get("/api/bootstrap")  # Warmup.
        durations, query_counts, payload_bytes = [], [], 0
        for _ in range(12):
            statements.clear()
            started = perf_counter()
            response = browser.get("/api/bootstrap")
            durations.append((perf_counter() - started) * 1000)
            assert response.status_code == 200
            payload_bytes = len(response.content)
            assert "PRIVATE INPUT" not in response.text and "Private solution" not in response.text
            assert len(response.json()["challenges"]) == count
            query_counts.append(len(statements))
        assert set(query_counts) == {3}, "Bootstrap must not grow one SQL query per task or proposal"
        statements.clear()
        started = perf_counter()
        detail = browser.get("/api/challenges/t1")
        detail_ms = (perf_counter() - started) * 1000
        assert detail.status_code == 200 and len(statements) == 2
        concurrent = []
        if count == 1000:
            def read(_):
                started = perf_counter()
                result = browser.get("/api/bootstrap")
                assert result.status_code == 200
                return (perf_counter() - started) * 1000
            with ThreadPoolExecutor(max_workers=10) as pool:
                concurrent = list(pool.map(read, range(20)))
        print(json.dumps({"tasks": count, "bootstrap_median_ms": round(median(durations), 2),
            "bootstrap_p95_ms": round(sorted(durations)[ceil(len(durations) * .95) - 1], 2),
            "bootstrap_bytes": payload_bytes, "bootstrap_select_queries": 3,
            "public_detail_ms": round(detail_ms, 2), "public_detail_select_queries": 2,
            "concurrency": 10 if concurrent else 1, "concurrent_requests": len(concurrent),
            "concurrent_median_ms": round(median(concurrent), 2) if concurrent else None,
            "concurrent_p95_ms": round(sorted(concurrent)[ceil(len(concurrent) * .95) - 1], 2) if concurrent else None}))
