import json
import shutil
import sqlite3
import zlib

import pytest
from fastapi.testclient import TestClient
from scripts.build_math_assessment_detail_db import SCHEMA_SQL
from scripts.package_math_assessment_vercel_data import assert_bounded_html_privacy

from app import main, settings
from app.main import app


def test_detail_endpoints_return_the_source_bounded_item(tmp_path, monkeypatch) -> None:
    database = tmp_path / "detail.sqlite"
    shutil.copyfile(settings.DEFAULT_DATABASE, database)
    item_id = "a" * 28
    with sqlite3.connect(database) as connection:
        case = connection.execute(
            "SELECT case_id, region FROM cases WHERE region != '' ORDER BY case_id LIMIT 1"
        ).fetchone()
        assert case is not None
        case_id = str(case[0])
        case_region = str(case[1])
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT INTO case_detail_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                "hwpx",
                "subject_section",
                "bounded",
                1,
                1,
                json.dumps(["함수 모델링 탐구"], ensure_ascii=False),
                1200,
                "b" * 64,
                0,
            ),
        )
        connection.execute(
            """
            UPDATE cases
            SET category = 'inquiry', priority_score = 68,
                review_score = 68, title_basis = 'source_detail',
                primary_task_name = '함수 모델링 탐구'
            WHERE case_id = ?
            """,
            (case_id,),
        )
        source_html = (
            "<section><h2>함수 모델링 탐구</h2><table>"
            "<tr><th>반영비율</th><td>20%</td></tr></table></section>"
            "<p>&lt;tr&gt;&lt;th&gt;평가요소&lt;/th&gt;&lt;th&gt;채점기준&lt;/th&gt;"
            "&lt;th&gt;배점&lt;/th&gt;&lt;/tr&gt;</p>"
            "<p>&lt;tr&gt;&lt;td&gt;근거&lt;/td&gt;&lt;td&gt;수학적 타당성&lt;/td&gt;"
            "&lt;td&gt;10점&lt;/td&gt;&lt;/tr&gt;</p>"
        )
        restored_source_html = (
            "<section><h2>함수 모델링 탐구</h2><table>"
            "<tr><th>반영비율</th><td>20%</td></tr></table></section>"
            "<table><tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>"
            "<tr><td>근거</td><td>수학적 타당성</td><td>10점</td></tr></table>"
        )
        rubric_html = ""
        restored_rubric_html = (
            "<table><tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>"
            "<tr><td>근거</td><td>수학적 타당성</td><td>10점</td></tr></table>"
        )
        connection.execute(
            """
            INSERT INTO assessment_items VALUES (
                ?, ?, 1, ?, ?, 'heading', 'bounded', 10, 1210,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                item_id,
                case_id,
                "함수 모델링 탐구",
                "함수 모델링 탐구",
                "함수를 이용해 실제 현상을 모델링한다.",
                "프로젝트",
                "5월",
                "20점",
                "20%",
                json.dumps(["[12대수01-01]"], ensure_ascii=False),
                zlib.compress(source_html.encode("utf-8")),
                zlib.compress(rubric_html.encode("utf-8")),
                len(source_html),
                len(rubric_html),
            ),
        )
        connection.executescript(
            """
            CREATE TABLE assessment_item_rankings (
                item_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                priority_signals_json TEXT NOT NULL
            ) WITHOUT ROWID;
            """
        )
        connection.execute(
            "INSERT INTO assessment_item_rankings VALUES (?, 'inquiry', 68, ?)",
            (item_id, json.dumps(["채점기준 원문 확인"], ensure_ascii=False)),
        )

    monkeypatch.setattr(main, "catalog_database_path", lambda: database)
    monkeypatch.setattr(main, "detail_catalog_database_path", lambda: database)
    client = TestClient(app)

    detail = client.get(f"/api/v1/cases/{case_id}/detail")
    assert detail.status_code == 200
    assert detail.json()["items"][0]["title"] == "함수 모델링 탐구"
    assert detail.json()["items"][0]["weight"] == "20%"

    item = client.get(f"/api/v1/assessment-items/{item_id}")
    assert item.status_code == 200
    payload = item.json()
    assert payload["source_html"] == restored_source_html
    assert payload["rubric_html"] == restored_rubric_html
    assert payload["has_rubric"] is True
    assert "saved_path" not in item.text

    curated = client.get(
        "/api/v1/curated",
        params={"category": "inquiry", "region": case_region, "limit": 20},
    )
    assert curated.status_code == 200
    curated_item = next(
        value for value in curated.json()["items"] if value["case_id"] == case_id
    )
    assert curated_item["item_id"] == item_id
    assert curated_item["title"] == "함수 모델링 탐구"
    assert curated_item["region"] == case_region

    outside_region = client.get(
        "/api/v1/curated",
        params={"category": "inquiry", "region": "없는 지역", "limit": 20},
    )
    assert outside_region.status_code == 200
    assert outside_region.json()["items"] == []

    assert client.get("/api/v1/assessment-items/" + "f" * 28).status_code == 404


def test_bundle_review_item_does_not_publish_source_html(tmp_path, monkeypatch) -> None:
    database = tmp_path / "bundle.sqlite"
    shutil.copyfile(settings.DEFAULT_DATABASE, database)
    item_id = "c" * 28
    with sqlite3.connect(database) as connection:
        case_id = str(connection.execute("SELECT case_id FROM cases LIMIT 1").fetchone()[0])
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            """
            INSERT INTO assessment_items VALUES (
                ?, ?, 1, '재검토 묶음', '재검토 묶음', 'section',
                'bundle_review', 0, 500, '', '', '', '', '', '[]', ?, ?, 37, 37
            )
            """,
            (
                item_id,
                case_id,
                zlib.compress(b"<table><tr><td>private bundle</td></tr></table>"),
                zlib.compress(b"<table><tr><td>private rubric</td></tr></table>"),
            ),
        )

    monkeypatch.setattr(main, "detail_catalog_database_path", lambda: database)
    response = TestClient(app).get(f"/api/v1/assessment-items/{item_id}")

    assert response.status_code == 404


def test_bounded_release_privacy_gate_rejects_high_risk_identifier(tmp_path) -> None:
    database = tmp_path / "privacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE assessment_items ("
            "item_id TEXT, extraction_status TEXT, source_html_zlib BLOB)"
        )
        connection.execute(
            "INSERT INTO assessment_items VALUES ('safe', 'bounded', ?)",
            (zlib.compress("<table><td>평가기준 10점</td></table>".encode()),),
        )

    assert_bounded_html_privacy(database)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO assessment_items VALUES ('unsafe', 'bounded', ?)",
            (zlib.compress("연락처 010-1234-5678".encode()),),
        )

    with pytest.raises(RuntimeError, match="personal-data release gate"):
        assert_bounded_html_privacy(database)
