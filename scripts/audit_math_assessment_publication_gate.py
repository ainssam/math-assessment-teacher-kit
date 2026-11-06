"""Audit the confirmed-only publication gate without inventing assessment names.

Every catalogue case is assigned one final state: confirmed for publication,
excluded because the requested mathematics-course boundary is contradicted, or
excluded because the source never exposes a bounded task name.  Only genuine
contract inconsistencies remain in the manual queue.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
import sys
import unicodedata
import zlib
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_titles_full import audit_flags, confidence
from scripts.math_assessment_detail_parser import (
    _clean_heading_title,
    explicit_segment_title,
)
from scripts.repair_math_assessment_titles import strict_source_titles

PLACEHOLDERS = {
    "",
    "구체적 과제명 미탐지",
    "수행평가 원문 구간",
    "수행평가명 미확정 · 원문 묶음",
}
MAX_PUBLIC_ITEMS_PER_CASE = 12


def compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣ⅠⅡ]", "", unicodedata.normalize("NFKC", value))


def visible_html_text(value: str) -> str:
    """Compare against what the teacher sees, not intervening HTML tag names."""

    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_publication_gate_audit.json",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_publication_manual_queue.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    item_rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.title, item.title_basis,
               item.extraction_status, item.source_html_zlib,
               cases.curriculum, cases.subject, cases.school_name,
               cases.title_basis AS case_title_basis
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        ORDER BY item.case_id, item.item_order
        """
    ).fetchall()
    case_rows = connection.execute(
        """
        SELECT cases.case_id, cases.curriculum, cases.subject, cases.school_name,
               cases.primary_task_name, cases.title_basis,
               SUM(items.extraction_status = 'bounded'
                   AND items.title_basis IN ('table', 'heading')) AS confirmed_items,
               SUM(items.extraction_status = 'source_mismatch_review') AS mismatch_items,
               COUNT(*) AS total_items
        FROM cases
        JOIN assessment_items items ON items.case_id = cases.case_id
        GROUP BY cases.case_id
        ORDER BY cases.case_id
        """
    ).fetchall()
    connection.close()

    item_counts: Counter[str] = Counter()
    case_counts: Counter[str] = Counter()
    queue: list[dict[str, object]] = []
    confirmed_case_ids: set[str] = set()
    for row in item_rows:
        public = (
            str(row["extraction_status"]) == "bounded"
            and str(row["title_basis"]) in {"table", "heading"}
        )
        if not public:
            item_counts["excluded_review_item"] += 1
            continue
        item_counts["confirmed_public_item"] += 1
        confirmed_case_ids.add(str(row["case_id"]))
        title = str(row["title"]).strip()
        reasons: list[str] = []
        if title in PLACEHOLDERS or not (2 <= len(compact(title)) <= 120):
            reasons.append("invalid_public_title")
        try:
            source_html = zlib.decompress(bytes(row["source_html_zlib"])).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            source_html = ""
            reasons.append("source_html_decode_failed")
        title_flags = audit_flags(title, str(row["title_basis"]))
        title_confidence = confidence(title_flags, str(row["title_basis"]))
        explicit_source_label = False
        if (
            title_confidence != "supported"
            and source_html
            and str(row["title_basis"]) == "table"
        ):
            explicit_title = explicit_segment_title(source_html)
            cleaned_explicit_title = (
                _clean_heading_title(explicit_title)[0] if explicit_title else ""
            )
            strict_title_keys = {
                compact(source_title) for source_title in strict_source_titles(source_html)
            }
            explicit_source_label = bool(
                compact(title) in strict_title_keys
                or (
                    explicit_title
                    and compact(cleaned_explicit_title) == compact(title)
                )
            )
        title_confidence = confidence(
            title_flags,
            str(row["title_basis"]),
            explicit_source_label=explicit_source_label,
        )
        if title_confidence == "reject":
            reasons.append("rejected_title_pattern")
        if compact(title) and compact(title) not in compact(visible_html_text(source_html)):
            reasons.append("title_not_present_in_source_html")
        if reasons:
            queue.append(
                {
                    "record_kind": "item",
                    "case_id": str(row["case_id"]),
                    "item_id": str(row["item_id"]),
                    "curriculum": str(row["curriculum"]),
                    "subject": str(row["subject"]),
                    "school_name": str(row["school_name"]),
                    "title": title,
                    "reasons": "|".join(reasons),
                }
            )

    for row in case_rows:
        case_id = str(row["case_id"])
        confirmed_items = int(row["confirmed_items"])
        mismatch_items = int(row["mismatch_items"])
        total_items = int(row["total_items"])
        if confirmed_items:
            state = "confirmed_public_case"
            if confirmed_items > MAX_PUBLIC_ITEMS_PER_CASE:
                queue.append(
                    {
                        "record_kind": "case",
                        "case_id": case_id,
                        "item_id": "",
                        "curriculum": str(row["curriculum"]),
                        "subject": str(row["subject"]),
                        "school_name": str(row["school_name"]),
                        "title": str(row["primary_task_name"]),
                        "reasons": "implausible_confirmed_item_count",
                    }
                )
            if str(row["title_basis"]) != "source_detail":
                queue.append(
                    {
                        "record_kind": "case",
                        "case_id": case_id,
                        "item_id": "",
                        "curriculum": str(row["curriculum"]),
                        "subject": str(row["subject"]),
                        "school_name": str(row["school_name"]),
                        "title": str(row["primary_task_name"]),
                        "reasons": "confirmed_item_without_confirmed_case_summary",
                    }
                )
        elif mismatch_items == total_items:
            state = "excluded_source_mismatch"
        elif mismatch_items:
            state = "excluded_mixed_or_cross_subject_bundle"
        else:
            state = "excluded_no_source_bounded_title"
        case_counts[state] += 1

    if confirmed_case_ids != {
        str(row["case_id"]) for row in case_rows if int(row["confirmed_items"]) > 0
    }:
        raise SystemExit("confirmed case/item reconciliation failed")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "database": str(args.database.resolve()),
        "case_counts": dict(sorted(case_counts.items())),
        "item_counts": dict(sorted(item_counts.items())),
        "manual_queue_count": len(queue),
        "target_manual_queue_below_50": len(queue) < 50,
        "publication_rule": (
            "Only bounded table/heading items whose visible source HTML contains the "
            "source-authored title, passes the conservative title audit, and belongs to a "
            "case with at most 12 public items. Excluded cases remain in the local audit "
            "database and are not public."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fieldnames = [
        "record_kind",
        "case_id",
        "item_id",
        "curriculum",
        "subject",
        "school_name",
        "title",
        "reasons",
    ]
    with args.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(queue)
    print(json.dumps(report, ensure_ascii=False))
    if not report["target_manual_queue_below_50"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
