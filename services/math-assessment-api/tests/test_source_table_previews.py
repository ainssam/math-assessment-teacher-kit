import hashlib

from app import source_table_previews as previews


def test_preview_is_bound_to_both_original_file_and_exact_item_html(monkeypatch):
    blob = b"archived compressed bytes"
    image = {"asset": "a" * 64 + ".webp", "page": 17, "width": 1024, "height": 1351}
    monkeypatch.setattr(
        previews,
        "REGISTRY",
        {
            "item": {
                "source_sha256": "original",
                "source_blob_sha256": hashlib.sha256(blob).hexdigest(),
                "source": [image],
                "rubric": [image],
                "source_excerpt_covered": True,
                "source_notes": ["원문에 적힌 과목과 일부 성취기준 코드가 다릅니다."],
            }
        },
    )
    result = previews.matching_previews("item", "original", blob)
    assert result["source_previews"][0]["url"] == "/source-tables/" + image["asset"]
    assert result["rubric_previews"][0]["page"] == 17
    assert result["source_excerpt_covered"] is True
    assert result["rubric_excerpt_covered"] is False
    assert result["source_notes"] == ["원문에 적힌 과목과 일부 성취기준 코드가 다릅니다."]
    assert not previews.matching_previews("item", "different original", blob)["source_previews"]
    assert not previews.matching_previews("item", "original", b"changed HTML")["source_previews"]
    assert not previews.matching_previews("item", "original", None)["source_previews"]
    assert not previews.matching_previews("item", "original", None)["source_excerpt_covered"]
    assert not previews.matching_previews("item", "different original", blob)["source_notes"]


def test_preview_rejects_external_and_traversal_paths(monkeypatch):
    blob = b"bytes"
    monkeypatch.setattr(
        previews,
        "REGISTRY",
        {
            "item": {
                "source_sha256": "original",
                "source_blob_sha256": hashlib.sha256(blob).hexdigest(),
                "source": [
                    {"asset": value, "page": 1, "width": 100, "height": 100}
                    for value in ("../private.webp", "https://example.org/a.webp")
                ],
            }
        },
    )
    assert previews.matching_previews("item", "original", blob)["source_previews"] == []


def test_complete_rubric_coverage_requires_its_own_exact_stored_html_hash(monkeypatch):
    source = b"source"
    rubric = b"rubric"
    monkeypatch.setattr(previews, "REGISTRY", {
        "item": {
            "source_sha256": "original",
            "source_blob_sha256": hashlib.sha256(source).hexdigest(),
            "rubric_blob_sha256": hashlib.sha256(rubric).hexdigest(),
            "rubric_excerpt_covered": True,
            "rubric": [{"asset": "a" * 64 + ".webp", "page": 1, "width": 100, "height": 100}],
        }
    })
    assert previews.matching_previews("item", "original", source, rubric)["rubric_excerpt_covered"]
    assert not previews.matching_previews("item", "original", source)["rubric_excerpt_covered"]
    changed = previews.matching_previews("item", "original", source, b"changed")
    assert not changed["rubric_excerpt_covered"]
