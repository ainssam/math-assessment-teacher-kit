from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def test_visitor_counter_returns_shared_today_and_total(monkeypatch) -> None:
    observed: dict[str, bool] = {}
    monkeypatch.setenv("MATH_ASSESSMENT_COUNTER_ORIGIN", "https://teacher-app.example")

    def fake_counts(*, increment_today: bool, increment_total: bool) -> dict[str, object]:
        observed.update(today=increment_today, total=increment_total)
        return {
            "date": "2026-08-12",
            "today": 7,
            "total": 42,
            "today_incremented": increment_today,
            "total_incremented": increment_total,
            "available": True,
        }

    monkeypatch.setattr(main_module, "visitor_counts", fake_counts)
    response = TestClient(app).post(
        "/api/v1/visitors?increment_today=true&increment_total=false",
        headers={"Origin": "https://teacher-app.example"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "date": "2026-08-12",
        "today": 7,
        "total": 42,
        "today_incremented": True,
        "total_incremented": False,
        "available": True,
    }
    assert observed == {"today": True, "total": False}


def test_visitor_counter_does_not_increment_for_foreign_origin(monkeypatch) -> None:
    observed: dict[str, bool] = {}
    monkeypatch.setenv("MATH_ASSESSMENT_COUNTER_ORIGIN", "https://teacher-app.example")

    def fake_counts(*, increment_today: bool, increment_total: bool) -> dict[str, object]:
        observed.update(today=increment_today, total=increment_total)
        return {
            "date": "2026-08-12",
            "today": 7,
            "total": 42,
            "today_incremented": False,
            "total_incremented": False,
            "available": True,
        }

    monkeypatch.setattr(main_module, "visitor_counts", fake_counts)
    response = TestClient(app).post(
        "/api/v1/visitors?increment_today=true&increment_total=true",
        headers={"Origin": "https://example.com"},
    )

    assert response.status_code == 200
    assert observed == {"today": False, "total": False}
