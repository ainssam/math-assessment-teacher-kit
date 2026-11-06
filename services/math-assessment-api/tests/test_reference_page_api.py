from fastapi.testclient import TestClient

from app.main import app


def test_reference_page_applies_subject_region_and_category_before_limiting() -> None:
    client = TestClient(app)
    subjects = client.get("/api/v1/subjects").json()["items"]
    selected = next(
        item
        for item in subjects
        if item["curriculum"] == "2022" and item["subject"] == "대수"
    )

    response = client.get(
        "/api/v1/references",
        params={
            "curriculum": selected["curriculum"],
            "subject": selected["subject"],
            "category": "inquiry",
            "limit": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert payload["total"] >= len(payload["items"])
    assert payload["subjects"]
    assert payload["facets"]["regions"]
    assert all(
        item["curriculum"] == "2022"
        and item["subject"] == "대수"
        and item["category"] == "inquiry"
        for item in payload["items"]
    )


def test_reference_page_can_be_narrowed_to_one_district() -> None:
    client = TestClient(app)
    base = {"curriculum": "2022", "subject": "대수", "category": "inquiry"}
    facets = client.get("/api/v1/references", params=base).json()["facets"]
    region = facets["regions"][0]["value"]
    district = client.get(
        "/api/v1/references", params={**base, "region": region}
    ).json()["facets"]["districts"][0]["value"]

    response = client.get(
        "/api/v1/references",
        params={**base, "region": region, "district": district},
    )

    assert response.status_code == 200
    assert response.json()["items"]
    assert all(
        item["region"] == region and item["district"] == district
        for item in response.json()["items"]
    )


def test_reference_page_rejects_district_without_region() -> None:
    response = TestClient(app).get(
        "/api/v1/references",
        params={"category": "inquiry", "district": "중구"},
    )

    assert response.status_code == 422
    assert "시도" in response.json()["detail"]
