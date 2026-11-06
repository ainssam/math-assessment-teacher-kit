"""Verify that table-boundary repair candidates preserve their source evidence.

This audit never changes either database.  It checks every inserted item against
its hidden parent bundle and fails when the visible text is not traceable to the
parent, a title is no longer present, or a review parent remains public.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zlib
from collections import Counter
from pathlib import Path

from lxml import html as lxml_html

from apply_math_assessment_table_boundary_repairs import item_identifier
from audit_math_assessment_table_structure import (
    SOURCE_HTML_MODULE,
    compact,
    element_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-database",
        type=Path,
        default=PROJECT_ROOT / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--candidate-database",
        type=Path,
        default=PROJECT_ROOT / ".tmp" / "math_assessment_catalog_detail_table_repair.sqlite",
    )
    parser.add_argument(
        "--proposals",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_table_boundary_repair_proposals.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_table_boundary_candidate_audit.json",
    )
    return parser.parse_args()


def source_text(blob: bytes | None) -> str:
    if not blob:
        return ""
    value = SOURCE_HTML_MODULE.restore_escaped_table_rows(
        zlib.decompress(blob).decode("utf-8")
    )
    root = lxml_html.fromstring(f"<div>{value}</div>")
    return compact(element_text(root))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    proposals = [
        json.loads(line)
        for line in args.proposals.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected: dict[str, tuple[str, str]] = {}
    parent_ids: set[str] = set()
    for proposal in proposals:
        parent_id = str(proposal["item_id"])
        parent_ids.add(parent_id)
        for order, candidate in enumerate(proposal.get("candidates") or [], 1):
            if candidate.get("accepted"):
                title = str(candidate.get("title") or "").strip()
                expected[item_identifier(parent_id, title, order)] = (parent_id, title)

    connection = sqlite3.connect(args.candidate_database)
    connection.row_factory = sqlite3.Row
    connection.execute("ATTACH DATABASE ? AS source_db", (str(args.source_database),))
    rows = connection.execute(
        """
        SELECT c.item_id, c.case_id, c.title, c.extraction_status,
               c.source_html_zlib, s.item_id AS source_item_id
        FROM assessment_items AS c
        LEFT JOIN source_db.assessment_items AS s ON s.item_id = c.item_id
        WHERE s.item_id IS NULL
        ORDER BY c.case_id, c.item_order
        """
    ).fetchall()

    counts: Counter[str] = Counter()
    failures: list[dict[str, str]] = []
    for row in rows:
        item_id = str(row["item_id"])
        mapping = expected.get(item_id)
        if not mapping:
            failures.append({"item_id": item_id, "reason": "inserted_item_not_in_proposals"})
            continue
        parent_id, expected_title = mapping
        parent = connection.execute(
            "SELECT extraction_status, source_html_zlib FROM assessment_items WHERE item_id = ?",
            (parent_id,),
        ).fetchone()
        if parent is None:
            failures.append({"item_id": item_id, "reason": "parent_missing"})
            continue
        candidate_text = source_text(row["source_html_zlib"])
        parent_text = source_text(parent["source_html_zlib"])
        checks = {
            "bounded": str(row["extraction_status"]) == "bounded",
            "parent_hidden": str(parent["extraction_status"]) == "table_structure_review",
            "title_exact": str(row["title"]) == expected_title,
            "title_in_source": compact(expected_title) in candidate_text,
            "source_text_in_parent": bool(candidate_text) and candidate_text in parent_text,
            "has_table": bool(re.search(r"<table\b", zlib.decompress(row["source_html_zlib"]).decode("utf-8"), re.I)),
        }
        for name, passed in checks.items():
            counts[f"{name}_passed"] += int(passed)
            if not passed:
                failures.append({"item_id": item_id, "parent_item_id": parent_id, "reason": name})
        counts["inserted_items"] += 1

    hidden_parent_count = connection.execute(
        f"SELECT COUNT(*) FROM assessment_items WHERE item_id IN ({','.join('?' for _ in parent_ids)}) AND extraction_status = 'table_structure_review'",
        tuple(sorted(parent_ids)),
    ).fetchone()[0]
    counts["expected_proposal_items"] = len(expected)
    counts["review_parents"] = len(parent_ids)
    counts["hidden_review_parents"] = int(hidden_parent_count)
    counts["failures"] = len(failures)

    report = {
        "schema_version": 1,
        "source_database": str(args.source_database.resolve()),
        "source_database_sha256": sha256(args.source_database),
        "candidate_database": str(args.candidate_database.resolve()),
        "candidate_database_sha256": sha256(args.candidate_database),
        "counts": dict(sorted(counts.items())),
        "gates": {
            "all_inserted_items_mapped": not any(
                row["reason"] == "inserted_item_not_in_proposals" for row in failures
            ),
            "all_inserted_source_text_traceable": not any(
                row["reason"] == "source_text_in_parent" for row in failures
            ),
            "all_inserted_titles_traceable": not any(
                row["reason"] in {"title_exact", "title_in_source"} for row in failures
            ),
            "all_review_parents_hidden": hidden_parent_count == len(parent_ids),
            "all_checks_pass": not failures and hidden_parent_count == len(parent_ids),
        },
        "failures": failures[:200],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["gates"]["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
