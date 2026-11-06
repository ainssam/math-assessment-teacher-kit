"""Audit whether parsed assessment items still match their selected math subject.

This is deliberately read-only.  It records direct achievement-code evidence
from each rendered source item and separates a definite other-subject code from
mixed or absent evidence.  The repair step may quarantine definite mismatches,
but this report remains the release gate and the teacher-review queue.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.math_assessment_detail_parser import (
    subjects_for_standard_codes,
    subject_code_key,
    visible_text,
)

STANDARD_CODE_RE = re.compile(
    r"\[\s*((?:10|12)(?:\s*-\s*)?[^\]\-]{1,20})\s*-\s*\d"
)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_subject_alignment_audit.json",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_subject_alignment_review_queue.csv",
    )
    return parser.parse_args()


def subject_codes(value: str) -> list[str]:
    return [subject_code_key(code) for code in STANDARD_CODE_RE.findall(value)]


def main() -> None:
    args = parse_args()
    database = args.database.resolve()
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT item.item_id, item.case_id, item.item_order, item.title,
                   item.title_basis, item.extraction_status, item.source_html_zlib,
                   case_record.curriculum, case_record.subject, case_record.school_name,
                   case_record.region, status.boundary_status
            FROM assessment_items item
            JOIN cases case_record USING (case_id)
            JOIN case_detail_status status USING (case_id)
            ORDER BY item.case_id, item.item_order
            """
        ).fetchall()

    counts: Counter[str] = Counter()
    case_classes: dict[str, set[str]] = defaultdict(set)
    queue: list[dict[str, str]] = []
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        html = zlib.decompress(bytes(row["source_html_zlib"])).decode("utf-8")
        codes = subject_codes(visible_text(html))
        selected_subject = str(row["subject"])
        code_subjects = subjects_for_standard_codes(codes)
        expected = selected_subject in code_subjects
        others = sorted(code_subjects - {selected_subject})
        if expected and others:
            classification = "mixed_subject_codes"
        elif expected:
            classification = "expected_subject_code"
        elif others:
            classification = "other_subject_code_only"
        elif codes:
            classification = "unmapped_math_code"
        else:
            classification = "no_achievement_code"
        counts[classification] += 1
        case_classes[str(row["case_id"])].add(classification)

        if classification in {"other_subject_code_only", "mixed_subject_codes", "unmapped_math_code"}:
            record = {
                "item_id": str(row["item_id"]),
                "case_id": str(row["case_id"]),
                "curriculum": str(row["curriculum"]),
                "subject": selected_subject,
                "school_name": str(row["school_name"]),
                "region": str(row["region"]),
                "item_order": str(row["item_order"]),
                "title": str(row["title"]),
                "title_basis": str(row["title_basis"]),
                "extraction_status": str(row["extraction_status"]),
                "boundary_status": str(row["boundary_status"]),
                "classification": classification,
                "detected_subjects": "|".join(sorted(code_subjects)),
                "codes": "|".join(codes[:12]),
            }
            queue.append(record)
            if len(samples[classification]) < 12:
                samples[classification].append(record)

    case_counts = Counter(
        "definite_other_subject_case"
        if "other_subject_code_only" in classes and "expected_subject_code" not in classes
        else "mixed_or_unmapped_case"
        if classes.intersection({"mixed_subject_codes", "unmapped_math_code"})
        else "expected_or_code_absent_case"
        for classes in case_classes.values()
    )
    unsafe_public_counts = Counter(
        record["classification"]
        for record in queue
        if record["extraction_status"] not in {"source_mismatch_review", "bundle_review"}
    )
    unsafe_public_items = sum(unsafe_public_counts.values())
    result = {
        "schema_version": 1,
        "database": str(database),
        "items": len(rows),
        "item_classification_counts": dict(sorted(counts.items())),
        "case_classification_counts": dict(sorted(case_counts.items())),
        "release_gate": {
            "unsafe_public_items": unsafe_public_items,
            "unsafe_public_items_by_classification": dict(sorted(unsafe_public_counts.items())),
            "all_unsafe_items_quarantined": unsafe_public_items == 0,
        },
        "samples": dict(sorted(samples.items())),
        "interpretation": (
            "Any item with another recognized mathematics course code, a mixture "
            "of course codes, or an unmapped achievement code remains review "
            "evidence and must not be publicly marked as bounded."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with args.queue.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(queue[0]) if queue else ["classification"])
        writer.writeheader()
        writer.writerows(queue)
    print(json.dumps({key: result[key] for key in ("items", "item_classification_counts", "case_classification_counts", "release_gate")}, ensure_ascii=False))
    if not result["release_gate"]["all_unsafe_items_quarantined"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
