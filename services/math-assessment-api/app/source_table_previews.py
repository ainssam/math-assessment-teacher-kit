"""Serve reviewed original-table crops only for the exact archived item version."""

import hashlib
import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("math_table_previews.json")
REGISTRY = json.loads(REGISTRY_PATH.read_text("utf-8"))["items"] if REGISTRY_PATH.is_file() else {}


def matching_previews(
    item_id: str,
    source_sha256: str,
    source_blob: bytes | None,
    rubric_blob: bytes | None = None,
) -> dict[str, list[dict] | list[str] | bool]:
    entry = REGISTRY.get(item_id, {})
    if (
        source_blob is None
        or entry.get("source_sha256") != source_sha256
        or entry.get("source_blob_sha256") != hashlib.sha256(source_blob).hexdigest()
    ):
        return {
            "source_previews": [],
            "rubric_previews": [],
            "source_preview_table_keys": [],
            "rubric_preview_table_keys": [],
            "source_excerpt_covered": False,
            "rubric_excerpt_covered": False,
            "source_notes": [],
        }
    output = {
        "source_notes": [
            note
            for note in entry.get("source_notes", [])
            if isinstance(note, str) and 0 < len(note) <= 1000
        ]
    }
    for kind in ("source", "rubric"):
        images = []
        for preview in entry.get(kind, []):
            if not re.fullmatch(r"[a-f0-9]{64}\.webp", preview.get("asset", "")):
                continue
            if not all(
                isinstance(preview.get(key), int) and preview[key] > 0
                for key in ("page", "width", "height")
            ):
                continue
            images.append(
                {
                    "url": "/source-tables/" + preview["asset"],
                    "page_context": preview.get("page_context") is True,
                    "rendered_from_hangul": preview.get("rendered_from_hangul") is True,
                    **{key: preview[key] for key in ("page", "width", "height")},
                }
            )
        output[kind + "_previews"] = images
        excerpt_matches = entry.get(kind + "_excerpt_covered") is True
        if kind == "rubric" and excerpt_matches:
            excerpt_matches = (
                rubric_blob is not None
                and entry.get("rubric_blob_sha256") == hashlib.sha256(rubric_blob).hexdigest()
            )
        output[kind + "_excerpt_covered"] = bool(images) and excerpt_matches
        output[kind + "_preview_table_keys"] = (
            [
                key
                for key in entry.get(kind + "_table_keys", [])
                if re.fullmatch(r"[0-9a-f]{16}", key)
            ]
            if images
            else []
        )
    return output
