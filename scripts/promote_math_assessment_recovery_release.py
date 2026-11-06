"""Promote a fully audited recovery catalogue to the local publish layer.

Current publish databases and manifests are copied to a timestamped archive
before any canonical path is replaced.  The script refuses promotion unless
all evidence, title, subject, detail, publication, and recovery-table gates
match the expected release counts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


EXPECTED = {
    "cases": 9096,
    "items": 24154,
    "public_cases": 4979,
    "public_items": 10981,
    "recovery_public_cases": 116,
    "recovery_public_items": 221,
}


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON object required: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_counts(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        counts: dict[str, object] = {
            "integrity": integrity,
            "cases": int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]),
        }
        if "assessment_items" in tables:
            counts.update(
                {
                    "items": int(
                        connection.execute("SELECT COUNT(*) FROM assessment_items").fetchone()[0]
                    ),
                    "case_details": int(
                        connection.execute("SELECT COUNT(*) FROM case_detail_status").fetchone()[0]
                    ),
                    "rankings": int(
                        connection.execute(
                            "SELECT COUNT(*) FROM assessment_item_rankings"
                        ).fetchone()[0]
                    ),
                    "null_source_html": int(
                        connection.execute(
                            "SELECT COUNT(*) FROM assessment_items WHERE source_html_zlib IS NULL"
                        ).fetchone()[0]
                    ),
                }
            )
        return counts
    finally:
        connection.close()


def checked_replace(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=target.name + "_promote_", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        shutil.copy2(source, temporary)
        expected_hash = sha256(source)
        if sha256(temporary) != expected_hash:
            raise SystemExit(f"promotion copy hash mismatch: {source}")
        os.replace(temporary, target)
        return expected_hash
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--detail-db", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--detail-manifest", type=Path, required=True)
    parser.add_argument("--title-audit", type=Path, required=True)
    parser.add_argument("--subject-audit", type=Path, required=True)
    parser.add_argument("--detail-audit", type=Path, required=True)
    parser.add_argument("--publication-gate", type=Path, required=True)
    parser.add_argument("--recovery-table-audit", type=Path, required=True)
    parser.add_argument("--combined-table-audit", type=Path, required=True)
    parser.add_argument("--completeness-summary", type=Path, required=True)
    parser.add_argument("--publish-dir", type=Path, default=root / "data" / "publish")
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    args = parser.parse_args()

    base_counts = database_counts(args.base_db)
    detail_counts = database_counts(args.detail_db)
    if base_counts != {"integrity": "ok", "cases": EXPECTED["cases"]}:
        raise SystemExit(f"unexpected base database counts: {base_counts}")
    if not (
        detail_counts.get("integrity") == "ok"
        and detail_counts.get("cases") == EXPECTED["cases"]
        and detail_counts.get("case_details") == EXPECTED["cases"]
        and detail_counts.get("items") == EXPECTED["items"]
        and detail_counts.get("rankings") == EXPECTED["items"]
        and detail_counts.get("null_source_html") == 0
    ):
        raise SystemExit(f"unexpected detail database counts: {detail_counts}")

    title = load_json(args.title_audit)
    subject = load_json(args.subject_audit)
    detail = load_json(args.detail_audit)
    publication = load_json(args.publication_gate)
    recovery_table = load_json(args.recovery_table_audit)
    combined_table = load_json(args.combined_table_audit)
    completeness = load_json(args.completeness_summary)
    if title.get("passed") is not True or any(
        int(value) for value in (title.get("hard_failures") or {}).values()
    ):
        raise SystemExit("title audit did not pass")
    release_gate = subject.get("release_gate") or {}
    if int(release_gate.get("unsafe_public_items") or 0) != 0:
        raise SystemExit("subject audit has unsafe public items")
    detail_gates = detail.get("gates") or {}
    if not detail_gates or not all(bool(value) for value in detail_gates.values()):
        raise SystemExit(f"detail audit gates did not pass: {detail_gates}")
    if (publication.get("case_counts") or {}).get("confirmed_public_case") != EXPECTED[
        "public_cases"
    ]:
        raise SystemExit("publication case count mismatch")
    if (publication.get("item_counts") or {}).get("confirmed_public_item") != EXPECTED[
        "public_items"
    ]:
        raise SystemExit("publication item count mismatch")
    if int(recovery_table.get("items_with_any_flag") or 0) != 0:
        raise SystemExit("recovery release still has structural table flags")
    checks = completeness.get("checks") or {}
    if not checks or not all(bool(value) for value in checks.values()):
        raise SystemExit(f"completeness checks did not pass: {checks}")

    publish_dir = args.publish_dir.resolve()
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = (args.archive_dir or publish_dir / "archive" / f"recovery-v1-{timestamp}").resolve()
    release_manifest = (
        args.release_manifest
        or publish_dir / "math_assessment_recovery_v1_release_manifest.json"
    ).resolve()
    if archive_dir.exists():
        raise SystemExit(f"archive directory already exists: {archive_dir}")
    archive_dir.mkdir(parents=True)

    canonical = {
        "base_db": publish_dir / "math_assessment_catalog.sqlite",
        "detail_db": publish_dir / "math_assessment_catalog_detail.sqlite",
        "base_manifest": publish_dir / "math_assessment_publish_manifest.json",
        "detail_manifest": publish_dir / "math_assessment_detail_manifest.json",
    }
    archived: list[dict[str, object]] = []
    for label, path in canonical.items():
        if not path.is_file():
            continue
        destination = archive_dir / path.name
        shutil.copy2(path, destination)
        if sha256(path) != sha256(destination):
            raise SystemExit(f"archive copy hash mismatch: {path}")
        archived.append(
            {
                "label": label,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        )

    promoted_hashes = {
        "base_db": checked_replace(args.base_db, canonical["base_db"]),
        "detail_db": checked_replace(args.detail_db, canonical["detail_db"]),
        "base_manifest": checked_replace(args.base_manifest, canonical["base_manifest"]),
        "detail_manifest": checked_replace(args.detail_manifest, canonical["detail_manifest"]),
    }
    promoted_counts = {
        "base": database_counts(canonical["base_db"]),
        "detail": database_counts(canonical["detail_db"]),
    }
    if promoted_counts["base"] != base_counts or promoted_counts["detail"] != detail_counts:
        raise SystemExit("promoted database counts differ from staged inputs")

    report = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "release": "recovery_v1",
        "expected": EXPECTED,
        "counts": promoted_counts,
        "promoted_sha256": promoted_hashes,
        "archived_previous_release": archived,
        "audits": {
            "title_passed": True,
            "unsafe_public_items": 0,
            "detail_gates_passed": True,
            "recovery_structural_flags": 0,
            "combined_structural_signal_items": int(
                combined_table.get("items_with_any_flag") or 0
            ),
            "publication_manual_queue": int(publication.get("manual_queue_count") or 0),
        },
        "policy": (
            "Recovery items are public only when source-bounded titles, subject alignment, "
            "traceability, and conservative table screening pass. Existing source files and "
            "the previous publish databases remain archived."
        ),
    }
    release_manifest.parent.mkdir(parents=True, exist_ok=True)
    release_manifest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
