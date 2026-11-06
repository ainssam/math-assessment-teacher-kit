"""Copy only publish-safe math assessment data into the Vercel API service."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = ROOT / "data" / "publish"
TARGET_DIRECTORY = ROOT / "services" / "math-assessment-api" / "data"
DETAIL_DATABASE = SOURCE_DIRECTORY / "math_assessment_catalog_detail.sqlite"
TABLE_STRUCTURE_QUEUE = (
    ROOT / "data" / "derived" / "math_assessment_table_structure_queue.csv"
)
INCLUDED_FILES = ("official_math_source_registry.json",)
CATALOG_DATABASE_NAME = "math_assessment_catalog.sqlite"
DETAIL_DATABASE_NAME = "math_assessment_catalog_detail.sqlite"
DATABASE_ARCHIVE_CHUNK_BYTES = 4_000_000
HIGH_RISK_PERSONAL_DATA_PATTERNS = {
    "resident_registration_number": re.compile(
        r"(?<![0-9])[0-9]{6}\s*-\s*[1-4][0-9]{6}(?![0-9])"
    ),
    "mobile_phone": re.compile(
        r"(?<![0-9])01[016789]\s*[-.)]\s*[0-9]{3,4}\s*-\s*[0-9]{4}(?![0-9])"
    ),
    "email": re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-database", type=Path, default=DETAIL_DATABASE)
    parser.add_argument(
        "--table-structure-queue", type=Path, default=TABLE_STRUCTURE_QUEUE
    )
    parser.add_argument("--target-directory", type=Path, default=TARGET_DIRECTORY)
    parser.add_argument(
        "--official-registry",
        type=Path,
        default=SOURCE_DIRECTORY / "official_math_source_registry.json",
    )
    return parser.parse_args()

CASE_SELECTS = (
    "case_id",
    "source_sha256",
    "curriculum",
    "curriculum_basis",
    "subject",
    "school_name",
    "region",
    "district",
    "academic_years_json",
    "grades_json",
    "semesters_json",
    "candidate_name",
    "source_url",
    "primary_task_name",
    "task_names_json",
    "action_tags_json",
    "rubric_marker_count",
    "achievement_standard_marker_count",
    "weight_or_points_marker_count",
    "assessment_method_marker_count",
    "review_score",
    "substr(evidence_excerpt, 1, 260) AS evidence_excerpt",
    "substr(summary_overview, 1, 180) AS summary_overview",
    "methods_json",
    "weight_summary",
    "standards_json",
    "criteria_json",
    "title_basis",
    "category",
    "priority_score",
    "priority_signals_json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_structure_review_item_ids(path: Path) -> set[str]:
    """Keep structurally unbounded whole-plan fragments out of the public package."""

    if not path.is_file():
        raise FileNotFoundError(
            "table structure audit queue is required before packaging: "
            f"{path}"
        )
    review_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            flags = set(str(row.get("flags") or "").split("|"))
            if "source:likely_unbounded_public_item" in flags:
                review_ids.add(str(row.get("item_id") or ""))
    review_ids.discard("")
    return review_ids


def package_catalog(
    source: Path,
    target: Path,
    *,
    include_source_html: bool,
    review_item_ids: set[str],
) -> None:
    """Build a read-only catalog, with source HTML only in the detail package."""
    source_html_select = (
        "CASE WHEN extraction_status = 'bounded' "
        "AND item_id NOT IN (SELECT item_id FROM publication_review_items) "
        "THEN source_html_zlib "
        "ELSE NULL END AS source_html_zlib"
        if include_source_html
        else "NULL AS source_html_zlib"
    )
    rubric_html_select = (
        "CASE WHEN extraction_status = 'bounded' "
        "AND item_id NOT IN (SELECT item_id FROM publication_review_items) "
        "THEN rubric_html_zlib "
        "ELSE NULL END AS rubric_html_zlib"
        if include_source_html
        else "NULL AS rubric_html_zlib"
    )
    with sqlite3.connect(target) as destination:
        destination.execute("PRAGMA journal_mode = OFF")
        destination.execute("PRAGMA synchronous = OFF")
        destination.execute("ATTACH DATABASE ? AS source", (str(source.resolve()),))
        destination.execute(
            "CREATE TEMP TABLE publication_review_items (item_id TEXT PRIMARY KEY)"
        )
        destination.executemany(
            "INSERT INTO publication_review_items VALUES (?)",
            ((item_id,) for item_id in sorted(review_item_ids)),
        )
        column_sql = ",\n    ".join(CASE_SELECTS)
        destination.executescript(
            f"""
            CREATE TABLE cases AS
            SELECT
                {column_sql}
            FROM source.cases;

            CREATE UNIQUE INDEX idx_cases_case_id ON cases(case_id);
            CREATE INDEX idx_cases_curriculum_subject_review
                ON cases(curriculum, subject, review_score DESC, case_id);
            CREATE INDEX idx_cases_category_priority
                ON cases(category, priority_score DESC, case_id);

            CREATE TABLE subject_stats AS SELECT * FROM source.subject_stats;
            CREATE UNIQUE INDEX idx_subject_stats_key
                ON subject_stats(curriculum, subject);

            CREATE TABLE subject_action_tags AS
            SELECT * FROM source.subject_action_tags;
            CREATE UNIQUE INDEX idx_subject_action_tags_key
                ON subject_action_tags(curriculum, subject, tag);

            CREATE TABLE case_detail_status AS
            SELECT * FROM source.case_detail_status;
            CREATE UNIQUE INDEX idx_case_detail_status_case
                ON case_detail_status(case_id);

            CREATE TABLE assessment_items AS
            SELECT item_id, case_id, item_order, title, title_raw, title_basis,
                   CASE WHEN item_id IN (SELECT item_id FROM publication_review_items)
                        THEN 'table_structure_review' ELSE extraction_status END
                        AS extraction_status,
                   source_start, source_end, overview, method,
                   timing, score, weight, standards_json,
                   {source_html_select},
                   {rubric_html_select},
                   source_html_char_count, rubric_html_char_count
            FROM source.assessment_items;
            CREATE UNIQUE INDEX idx_assessment_items_item
                ON assessment_items(item_id);
            CREATE INDEX idx_assessment_items_case_order
                ON assessment_items(case_id, item_order);
            CREATE INDEX idx_assessment_items_ranked
                ON assessment_items(extraction_status, title_basis, item_id, case_id);

            CREATE TABLE assessment_item_rankings AS
            SELECT * FROM source.assessment_item_rankings;
            CREATE UNIQUE INDEX idx_assessment_item_rankings_item
                ON assessment_item_rankings(item_id);
            CREATE INDEX idx_assessment_item_rankings_category_priority
                ON assessment_item_rankings(category, priority_score DESC, item_id);
            """
        )
        destination.execute("DETACH DATABASE source")
        destination.execute("VACUUM")


def package_catalog_archive(database: Path, target_directory: Path) -> None:
    archive_name = f"{database.name}.gz"
    temporary = target_directory / f"{archive_name}.partial"
    with database.open("rb") as source, temporary.open("wb") as target:
        with gzip.GzipFile(
            filename="", mode="wb", compresslevel=9, fileobj=target, mtime=0
        ) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
    try:
        with temporary.open("rb") as stream:
            for index, chunk in enumerate(
                iter(lambda: stream.read(DATABASE_ARCHIVE_CHUNK_BYTES), b"")
            ):
                target = target_directory / f"{archive_name}.part-{index:02d}"
                target.write_bytes(chunk)
    finally:
        temporary.unlink(missing_ok=True)


def catalog_counts(database_path: Path) -> dict[str, int]:
    """Read release counts without ever creating a missing SQLite file."""
    database_uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as database:
        return {
            "cases": int(database.execute("SELECT COUNT(*) FROM cases").fetchone()[0]),
            "case_details": int(
                database.execute("SELECT COUNT(*) FROM case_detail_status").fetchone()[0]
            ),
            "assessment_items": int(
                database.execute("SELECT COUNT(*) FROM assessment_items").fetchone()[0]
            ),
            "assessment_item_rankings": int(
                database.execute("SELECT COUNT(*) FROM assessment_item_rankings").fetchone()[0]
            ),
            "regions": int(
                database.execute(
                    "SELECT COUNT(DISTINCT region) FROM cases WHERE region != ''"
                ).fetchone()[0]
            ),
            "districts": int(
                database.execute(
                    "SELECT COUNT(DISTINCT district) FROM cases WHERE district != ''"
                ).fetchone()[0]
            ),
        }


def database_manifest_record(database_path: Path) -> dict[str, object]:
    """Describe a database even when only its archive chunks are deployed."""
    return {
        "name": database_path.name,
        "bytes": database_path.stat().st_size,
        "sha256": sha256(database_path),
        "packaged_as": f"{database_path.name}.gz.part-*",
    }


def assert_bounded_html_privacy(database_path: Path) -> None:
    """Block release when a public bounded section contains high-risk identifiers."""
    database_uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    findings: dict[str, int] = {name: 0 for name in HIGH_RISK_PERSONAL_DATA_PATTERNS}
    with sqlite3.connect(database_uri, uri=True) as database:
        rows = database.execute(
            "SELECT source_html_zlib FROM assessment_items "
            "WHERE extraction_status = 'bounded' AND source_html_zlib IS NOT NULL"
        )
        for (payload,) in rows:
            source_html = zlib.decompress(payload).decode("utf-8", errors="replace")
            for name, pattern in HIGH_RISK_PERSONAL_DATA_PATTERNS.items():
                findings[name] += int(pattern.search(source_html) is not None)
    detected = {name: count for name, count in findings.items() if count}
    if detected:
        raise RuntimeError(
            "bounded source HTML failed the personal-data release gate: "
            f"{detected}"
        )


def main() -> None:
    args = parse_args()
    root = ROOT.resolve()
    target = args.target_directory.resolve()
    if not target.is_relative_to(root) or target == root:
        raise RuntimeError(f"unsafe package target: {target}")

    detail_database = args.detail_database.resolve()
    table_structure_queue = args.table_structure_queue.resolve()
    sources = [
        detail_database,
        table_structure_queue,
        args.official_registry.resolve(),
    ]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"publish-safe source is missing: {missing}")
    assert_bounded_html_privacy(detail_database)
    review_item_ids = table_structure_review_item_ids(table_structure_queue)

    if target.is_dir():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    catalog_path = target / CATALOG_DATABASE_NAME
    detail_path = target / DETAIL_DATABASE_NAME
    package_catalog(
        detail_database,
        catalog_path,
        include_source_html=False,
        review_item_ids=review_item_ids,
    )
    package_catalog(
        detail_database,
        detail_path,
        include_source_html=True,
        review_item_ids=review_item_ids,
    )
    for source in sources[2:]:
        shutil.copy2(source, target / source.name)

    package_catalog_archive(catalog_path, target)
    package_catalog_archive(detail_path, target)
    database_counts = catalog_counts(catalog_path)
    database_records = [
        database_manifest_record(path) for path in (catalog_path, detail_path)
    ]
    # Windows may retain a read handle while a local preview is running.  The
    # archive parts are authoritative for deployment, so a leftover local copy
    # is harmless and is ignored by the staging script.
    for path in (catalog_path, detail_path):
        try:
            path.unlink()
        except PermissionError:
            pass

    packaged = sorted(path for path in target.iterdir() if path.is_file())
    manifest = {
        "schema_version": 1,
        "purpose": "Vercel runtime package for the read-only math assessment API",
        "excluded": [
            "schoolinfo full raw documents",
            "non-math and non-assessment source sections",
            "official curriculum PDFs",
            "local paths",
        ],
        "included": [
            "source-bounded math performance-assessment HTML tables",
            "exact assessment names and source field values",
            "compressed rubric tables",
        ],
        "public_excerpt_limit": 260,
        "database_counts": database_counts,
        "table_structure_review_item_count": len(review_item_ids),
        "files": database_records + [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in packaged
            if path.name not in {CATALOG_DATABASE_NAME, DETAIL_DATABASE_NAME}
        ],
    }
    (target / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
