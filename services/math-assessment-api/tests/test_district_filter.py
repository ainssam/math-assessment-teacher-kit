from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_district_facets_and_case_filter_are_source_backed() -> None:
    subjects = client.get("/api/v1/subjects").json()["items"]
    selected_subject = next(
        item for item in subjects if item["curriculum"] == "2022" and item["documents"] > 0
    )
    base = {"curriculum": "2022", "subject": selected_subject["subject"]}
    initial = client.get("/api/v1/facets", params=base)
    assert initial.status_code == 200
    region = initial.json()["regions"][0]["value"]

    narrowed = client.get("/api/v1/facets", params={**base, "region": region})
    assert narrowed.status_code == 200
    districts = narrowed.json()["districts"]
    assert districts
    district = districts[0]

    response = client.get(
        "/api/v1/cases",
        params={**base, "region": region, "district": district["value"], "limit": 30},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == district["count"]
    assert all(
        item["region"] == region and item["district"] == district["value"]
        for item in payload["items"]
    )
