"""Validate the published math-assessment catalog beyond schema checks."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from build_math_assessment_publish_db import (
    assessment_category,
    task_name_is_rejected,
)

PLACEHOLDER = "구체적 과제명 미탐지"
PARSER_ARTIFACT_RE = re.compile(
    r"gfedcb?|(?:row|col|l)?span\s*=|(?:^|<)t[dh]\s+|평가영역\S",
    re.IGNORECASE,
)
REPEATED_FRAGMENT_RE = re.compile(r"(.{18,}?)(?:\s*[·|]\s*)\1")


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument("--top-limit", type=int, default=15)
    parser.add_argument("--expected-case-count", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row

    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    rows = connection.execute(
        """
        SELECT case_id, primary_task_name, task_names_json, category,
               summary_overview, source_url, priority_score, school_name, subject
        FROM cases
        """
    ).fetchall()
    fts_rows = connection.execute("SELECT COUNT(*) FROM cases_fts").fetchone()[0]
    expected_case_count = args.expected_case_count
    if expected_case_count is None:
        metadata_row = connection.execute(
            "SELECT value_json FROM metadata WHERE key = 'source_catalog_rows'"
        ).fetchone()
        expected_case_count = (
            int(json.loads(str(metadata_row[0]))) if metadata_row else len(rows)
        )

    rejected_candidates: list[dict[str, str]] = []
    compact_duplicates: list[dict[str, str]] = []
    category_mismatches: list[dict[str, str]] = []
    parser_artifacts: list[dict[str, str]] = []
    repeated_overviews: list[str] = []
    primary_mismatches: list[str] = []
    invalid_source_urls: list[str] = []
    category_counts: Counter[str] = Counter()

    for row in rows:
        names = json.loads(row["task_names_json"] or "[]")
        if not isinstance(names, list):
            raise SystemExit(f"task_names_json is not a list: {row['case_id']}")
        if row["primary_task_name"] != PLACEHOLDER and (
            not names or names[0] != row["primary_task_name"]
        ):
            primary_mismatches.append(row["case_id"])

        seen_compact: dict[str, str] = {}
        for name in names:
            name = str(name)
            if task_name_is_rejected(name):
                rejected_candidates.append({"case_id": row["case_id"], "name": name})
            if PARSER_ARTIFACT_RE.search(name):
                parser_artifacts.append({"case_id": row["case_id"], "name": name})
            compact = re.sub(r"\s+", "", name)
            previous = seen_compact.get(compact)
            if previous is not None and previous != name:
                compact_duplicates.append(
                    {"case_id": row["case_id"], "first": previous, "second": name}
                )
            seen_compact[compact] = name

        expected_category = assessment_category(row["primary_task_name"], {}, "")
        if expected_category != row["category"]:
            category_mismatches.append(
                {
                    "case_id": row["case_id"],
                    "title": row["primary_task_name"],
                    "stored": row["category"],
                    "expected": expected_category,
                }
            )
        if row["category"]:
            category_counts[row["category"]] += 1

        overview = row["summary_overview"] or ""
        if overview == "세부 평가 내용" or REPEATED_FRAGMENT_RE.search(overview):
            repeated_overviews.append(row["case_id"])
        if not str(row["source_url"]).startswith("https://www.schoolinfo.go.kr/"):
            invalid_source_urls.append(row["case_id"])

    top_samples: dict[str, list[dict[str, object]]] = {}
    for category in (
        "inquiry",
        "modeling",
        "problem",
        "presentation",
        "portfolio",
        "reading",
    ):
        top_samples[category] = [
            dict(sample)
            for sample in connection.execute(
                """
                SELECT school_name, subject, primary_task_name, priority_score
                FROM cases
                WHERE category = ? AND primary_task_name <> ?
                ORDER BY priority_score DESC, evidence_score DESC, case_id
                LIMIT ?
                """,
                (category, PLACEHOLDER, args.top_limit),
            )
        ]

    failures = {
        "integrity": 0 if integrity == "ok" else 1,
        "case_count": 0 if len(rows) == expected_case_count else 1,
        "fts_count": 0 if fts_rows == len(rows) else 1,
        "rejected_candidates": len(rejected_candidates),
        "compact_duplicates": len(compact_duplicates),
        "category_mismatches": len(category_mismatches),
        "parser_artifacts": len(parser_artifacts),
        "repeated_overviews": len(repeated_overviews),
        "primary_mismatches": len(primary_mismatches),
        "invalid_source_urls": len(invalid_source_urls),
    }
    result = {
        "database": str(args.database),
        "integrity": integrity,
        "cases": len(rows),
        "fts_rows": fts_rows,
        "category_counts": dict(sorted(category_counts.items())),
        "failures": failures,
        "failure_samples": {
            "rejected_candidates": rejected_candidates[:20],
            "compact_duplicates": compact_duplicates[:20],
            "category_mismatches": category_mismatches[:20],
            "parser_artifacts": parser_artifacts[:20],
        },
        "top_samples": top_samples,
        "passed": not any(failures.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
