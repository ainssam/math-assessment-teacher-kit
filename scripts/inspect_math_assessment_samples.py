"""Print compact public-catalog samples for deterministic quality review."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/publish/math_assessment_catalog.sqlite"),
    )
    parser.add_argument("--curriculum", default="2022")
    parser.add_argument("--subject", default="미적분Ⅰ")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--limit", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    if args.case_id:
        where_clause = "case_id = ?"
        parameters: tuple[object, ...] = (args.case_id, args.limit)
    else:
        where_clause = "curriculum = ? AND subject = ?"
        parameters = (args.curriculum, args.subject, args.limit)
    # The interpolated clause is selected from the two constants above.
    rows = connection.execute(
        f"""
        SELECT
            case_id,
            source_sha256,
            primary_task_name,
            task_names_json,
            action_tags_json,
            evidence_score,
            length(evidence_excerpt) AS excerpt_chars,
            evidence_excerpt
        FROM cases
        WHERE {where_clause}
        ORDER BY evidence_score DESC, school_name, case_id
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
