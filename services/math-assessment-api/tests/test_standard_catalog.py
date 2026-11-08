import hashlib
import json
import unicodedata

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.standard_catalog import REGISTRIES, STANDARDS, source_standard_codes


def test_standard_matching_normalizes_roman_numerals_without_crossing_subjects() -> None:
    raw = json.dumps(["[12미적Ⅰ-02-01]", "[12미적I-02-01]", "[12대수01-01]"])
    assert source_standard_codes(raw, "미적분Ⅰ") == {"12미적I-02-01"}
    assert source_standard_codes(raw, "대수") == {"12대수01-01"}


def test_standard_matching_rejects_truncated_and_unpublished_codes() -> None:
    raw = json.dumps(["[12미적Ⅱ-02-01]", "[12미적I-02-010]", "[112미적I-02-01]", "[12미적I-99-99]"])
    assert source_standard_codes(raw, "미적분Ⅰ") == set()
    assert len(STANDARDS["2022"]) == 254
    assert STANDARDS["2022"]["12미적I-02-01"]["text"] == "미분계수를 이해하고, 이를 구할 수 있다."


@pytest.mark.parametrize("curriculum", ["2015", "2022"])
def test_every_published_standard_matches_only_its_course(curriculum: str) -> None:
    registry = REGISTRIES[curriculum]
    for entry in registry["standards"]:
        raw = json.dumps([entry["code"]])
        assert entry["curriculum"] == curriculum
        assert source_standard_codes(raw, entry["subject"], curriculum) == {entry["key"]}
        assert entry["key"] == unicodedata.normalize("NFKC", entry["code"][1:-1])
        other = next(subject for subject in registry["subjects"] if subject != entry["subject"])
        assert source_standard_codes(raw, other, curriculum) == set()


def test_curriculum_and_course_boundaries_do_not_merge() -> None:
    assert len(STANDARDS["2015"]) == 199
    assert sum(len(value["subjects"]) for value in REGISTRIES.values()) == 25
    assert sum(len(value) for value in STANDARDS.values()) == 453
    # Identical codes can name different official criteria across revisions.
    assert STANDARDS["2015"]["12기하01-01"]["text"] != STANDARDS["2022"]["12기하01-01"]["text"]
    assert source_standard_codes(
        json.dumps(["[10공수1-01-01]", "[10공수2-01-01]"]), "공통수학2"
    ) == {"10공수2-01-01"}
    assert source_standard_codes(json.dumps(["[12미적Ⅰ-02-01]", "[12미적Ⅱ-02-01]"]), "미적분Ⅱ") == {
        "12미적II-02-01"
    }
    assert source_standard_codes(
        json.dumps(["[12수학Ⅰ01-01]", "[12수학Ⅱ01-01]"]), "수학Ⅱ", "2015"
    ) == {"12수학II01-01"}
    assert source_standard_codes(json.dumps(["[10공수1-01-01]"]), "공통수학1", "2015") == set()


def test_2015_ai_addition_preserves_all_186_existing_official_criteria() -> None:
    original = [
        entry for entry in REGISTRIES["2015"]["standards"] if entry["subject"] != "인공지능 수학"
    ]
    assert len(original) == 186
    canonical = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        "25ef80ab8b2de2e7497a78e8e127c0bb1e5bb56d31411c28dc9eda8dfdcc7b26"
    )
    ai = [entry for entry in STANDARDS["2015"].values() if entry["subject"] == "인공지능 수학"]
    assert len(ai) == 13
    assert STANDARDS["2015"]["12인수01-01"]["text"] == (
        "인공지능의 발전에 기여한 역사적 사례에서 수학이 어떻게 활용되었는지를 이해한다."
    )
    assert STANDARDS["2015"]["12인수01-01"]["text"] != (STANDARDS["2022"]["12인수01-01"]["text"])


def test_only_2015_ai_uses_its_2020_236_notice_source() -> None:
    registry = REGISTRIES["2015"]
    assert set(registry["subject_sources"]) == {"인공지능 수학"}
    ai_source = registry["subject_sources"]["인공지능 수학"]
    assert "2020-236" in ai_source["source_title"]
    assert ai_source["source_sha256"] == (
        "1cb1623f270b37ed88475237ce92989519fd1568cb20103d4850331a31419fcb"
    )
    assert "2015-74" in registry["source_title"]
    with TestClient(app) as client:
        ai = client.get(
            "/api/v1/standard-references",
            params={"curriculum": "2015", "subject": "인공지능 수학", "limit": 1},
        )
        geometry = client.get(
            "/api/v1/standard-references",
            params={"curriculum": "2015", "subject": "기하", "limit": 1},
        )
    assert ai.status_code == geometry.status_code == 200
    assert ai.json()["source_url"] == ai_source["source_url"]
    assert geometry.json()["source_url"] == registry["source_url"]


def test_standard_route_validates_course_against_curriculum() -> None:
    with TestClient(app) as client:
        for curriculum, subject in [("2015", "공통수학1"), ("2022", "수학Ⅱ"), ("2022", "unknown")]:
            response = client.get(
                "/api/v1/standard-references", params={"curriculum": curriculum, "subject": subject}
            )
            assert response.status_code == 422
        assert client.get("/api/v1/standard-references?curriculum=unknown").status_code == 422


@pytest.mark.parametrize("curriculum", ["2015", "2022"])
def test_standard_route_supports_all_curriculum_courses(curriculum: str) -> None:
    with TestClient(app) as client:
        for subject in REGISTRIES[curriculum]["subjects"]:
            response = client.get(
                "/api/v1/standard-references",
                params={"curriculum": curriculum, "subject": subject, "limit": 1},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["curriculum"] == curriculum
            assert payload["subject"] == subject
            assert len(payload["standards"]) == sum(
                entry["subject"] == subject for entry in STANDARDS[curriculum].values()
            )
            for item in payload["items"]:
                assert payload["standard"]["key"] in source_standard_codes(
                    json.dumps(item["standards"]), subject, curriculum
                )


def test_standard_route_does_not_fallback_when_requested_code_is_unknown() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/standard-references", params={"standard": "unknown"})
    assert response.status_code == 200
    assert response.json()["standard"] is None
    assert response.json()["items"] == []
