import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.settings import catalog_database_path


def test_health_reports_math_assessment_service_identity() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "math-assessment-api",
        "version": "0.3.0",
    }
    serialized = response.text.lower()
    assert "database_url" not in serialized
    assert "api_key" not in serialized
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_deployment_health_alias_is_available() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_product_metadata_keeps_raw_documents_out_of_contract() -> None:
    response = TestClient(app).get("/api/v1/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product"] == "2026 수학 수행평가 아이디어 아카이브"
    assert payload["development_phase"] == "수학 수행평가 원문 탐색기"
    assert payload["catalog_cases"] == 9096
    with sqlite3.connect(catalog_database_path()) as connection:
        expected_public_cases = connection.execute(
            """
            SELECT COUNT(DISTINCT case_id) FROM assessment_items
            WHERE extraction_status = 'bounded'
              AND title_basis IN ('table', 'heading')
            """
        ).fetchone()[0]
        expected_public_items = connection.execute(
            """
            SELECT COUNT(*) FROM assessment_items
            WHERE extraction_status = 'bounded'
              AND title_basis IN ('table', 'heading')
            """
        ).fetchone()[0]
        expected_items = connection.execute(
            "SELECT COUNT(*) FROM assessment_items"
        ).fetchone()[0]
    assert payload["public_cases"] == expected_public_cases
    assert payload["public_items"] == expected_public_items
    assert payload["excluded_items"] == expected_items - expected_public_items
    assert sum(payload["excluded_reasons"].values()) == payload["excluded_items"]
    assert "raw_path" not in payload
    assert "source_text" not in payload
