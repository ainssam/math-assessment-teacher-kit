"""Validate the publish database against the final source-catalog evidence."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def query_value(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> object:
    row = connection.execute(sql, parameters).fetchone()
    return row[0] if row else None


def uses_index(plan_rows: list[sqlite3.Row], index_name: str) -> bool:
    return any(index_name in str(row[3]) for row in plan_rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--source-validation",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_catalog_validation_v2.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_publish_validation.json",
    )
    args = parser.parse_args()
    if not args.database.is_file() or not args.source_validation.is_file():
        raise SystemExit("publish database or source validation is missing")

    source = json.loads(args.source_validation.read_text(encoding="utf-8"))
    expected_cases = int(source.get("counts", {}).get("strict_rows") or 0)
    expected_schools = int(source.get("counts", {}).get("schools") or 0)
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    case_count = int(query_value(connection, "SELECT COUNT(*) FROM cases") or 0)
    subject_count = int(query_value(connection, "SELECT COUNT(*) FROM subject_stats") or 0)
    coverage_subject_count = int(
        query_value(
            connection,
            "SELECT COUNT(*) FROM subject_stats WHERE coverage_found IS NOT NULL",
        )
        or 0
    )
    fts_count = int(query_value(connection, "SELECT COUNT(*) FROM cases_fts") or 0)
    max_excerpt = int(
        query_value(connection, "SELECT COALESCE(MAX(excerpt_char_count), 0) FROM cases") or 0
    )
    local_path_leaks = int(
        query_value(
            connection,
            """
            SELECT COUNT(*) FROM cases
            WHERE evidence_excerpt LIKE '%data/raw/%'
               OR evidence_excerpt LIKE '%C:\\Users\\%'
               OR source_url LIKE 'file:%'
            """,
        )
        or 0
    )
    invalid_source_urls = int(
        query_value(
            connection,
            """
            SELECT COUNT(*) FROM cases
            WHERE source_url != '' AND source_url NOT LIKE '%schoolinfo.go.kr%'
            """,
        )
        or 0
    )
    distinct_case_ids = int(
        query_value(connection, "SELECT COUNT(DISTINCT case_id) FROM cases") or 0
    )
    integrity = str(query_value(connection, "PRAGMA integrity_check") or "")
    subject_plan = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT case_id FROM cases
        WHERE curriculum = ? AND subject = ?
        ORDER BY review_score DESC, case_id LIMIT 20
        """,
        ("2022", "대수"),
    ).fetchall()
    tag_plan = connection.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT case_id FROM case_action_tags WHERE tag = ? LIMIT 20
        """,
        ("탐구",),
    ).fetchall()
    database_schema = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type IN ('table', 'view')"
        )
    }
    forbidden_schema_names = {
        name for name in database_schema if "raw" in name.lower() or "full_text" in name.lower()
    }
    metadata_school_count = expected_schools
    connection.close()

    checks = {
        "source_validation_passed": source.get("passed") is True,
        "integrity_check": integrity == "ok",
        "case_count_matches": case_count == expected_cases,
        "case_ids_unique": distinct_case_ids == case_count,
        "subject_groups_include_24_courses_and_shared_groups": subject_count >= 24,
        "coverage_subject_groups_match_24_courses": coverage_subject_count == 24,
        "fts_rows_match_cases": fts_count == case_count,
        "excerpt_length_limited": max_excerpt <= 902,
        "no_local_path_leaks": local_path_leaks == 0,
        "source_urls_are_schoolinfo_only": invalid_source_urls == 0,
        "no_forbidden_raw_schema": not forbidden_schema_names,
        "subject_filter_uses_index": uses_index(
            subject_plan, "idx_cases_curriculum_subject_review"
        ),
        "tag_filter_uses_index": uses_index(tag_plan, "idx_case_action_tags_tag_case"),
    }
    result = {
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "schools_in_source_validation": metadata_school_count,
            "cases": case_count,
            "subjects": subject_count,
            "coverage_subjects": coverage_subject_count,
            "fts_rows": fts_count,
            "maximum_excerpt_chars": max_excerpt,
            "local_path_leaks": local_path_leaks,
            "invalid_source_urls": invalid_source_urls,
        },
        "query_plans": {
            "subject_filter": [str(row[3]) for row in subject_plan],
            "tag_filter": [str(row[3]) for row in tag_plan],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
