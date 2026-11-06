"""Apply audited table-boundary proposals to a new SQLite candidate database.

The source database is never edited.  Unbounded parent items remain in the
candidate database with ``table_structure_review`` status, while accepted
source-labelled fragments become individually bounded items.  Existing clean
siblings win over duplicate proposals.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
import zlib
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_math_assessment_table_structure import (
    SOURCE_HTML_MODULE,
    compact,
    element_text,
)
from math_assessment_detail_parser import _exact_fields
from lxml import html as lxml_html

PROJECT_ROOT = Path(__file__).resolve().parents[1]
rubric_tables_from_source_html = SOURCE_HTML_MODULE.rubric_tables_from_source_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "publish"
        / "math_assessment_catalog_detail.sqlite",
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
        / ".tmp"
        / "math_assessment_catalog_detail_table_repair.sqlite",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_table_boundary_repair_apply_report.json",
    )
    return parser.parse_args()


def title_key(value: str) -> str:
    return re.sub(
        r"[^0-9A-Za-z가-힣ⅠⅡ]",
        "",
        unicodedata.normalize("NFKC", value),
    )


def item_identifier(parent_item_id: str, title: str, candidate_order: int) -> str:
    payload = f"table-repair|{parent_item_id}|{candidate_order}|{title_key(title)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:28]


def visible_cells(source_html: str) -> list[list[str]]:
    root = lxml_html.fromstring(f"<div>{source_html}</div>")
    return [
        [element_text(cell) for cell in row.xpath("./th|./td")]
        for row in root.xpath(".//tr")
    ]


def exact_field(rows: list[list[str]], labels: tuple[str, ...]) -> str:
    label_keys = {compact(label) for label in labels}
    for row in rows:
        for index, value in enumerate(row):
            if compact(value) not in label_keys:
                continue
            for candidate in row[index + 1 :]:
                clean = re.sub(r"\s+", " ", candidate).strip(" |:：")
                if clean:
                    return clean[:500]
    return ""


def achievement_standards(source_html: str) -> list[str]:
    root = lxml_html.fromstring(f"<div>{source_html}</div>")
    visible = element_text(root)
    output: list[str] = []
    for match in re.finditer(
        r"\[\s*(12\s*[A-Za-z가-힣ⅠⅡ]{1,16}\s*\d{2}\s*[-‐‑‒–—]\s*\d{2})\s*\]",
        visible,
    ):
        value = re.sub(r"\s+", "", match.group(1)).replace("–", "-").replace("—", "-")
        formatted = f"[{value}]"
        if formatted not in output:
            output.append(formatted)
    return output


def load_proposals(path: Path) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"proposal row must be object: {path}:{line_number}")
            output.append(row)
    return output


def synchronize_summaries(connection: sqlite3.Connection) -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    module = importlib.import_module("scripts.build_math_assessment_detail_db")
    module.synchronize_case_summaries(connection)


def main() -> None:
    args = parse_args()
    proposals = load_proposals(args.proposals)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.partial")
    temporary.unlink(missing_ok=True)
    shutil.copy2(args.database, temporary)

    connection = sqlite3.connect(temporary)
    connection.row_factory = sqlite3.Row
    counts: Counter[str] = Counter()
    inserted_by_parent: defaultdict[str, list[str]] = defaultdict(list)
    affected_cases: set[str] = set()
    parent_ids = {str(row["item_id"]) for row in proposals}
    existing_titles: defaultdict[str, set[str]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT item_id, case_id, title FROM assessment_items
        WHERE extraction_status = 'bounded'
          AND title_basis IN ('table', 'heading')
        """
    ):
        if str(row["item_id"]) not in parent_ids:
            existing_titles[str(row["case_id"])].add(title_key(str(row["title"])))

    original_case_items: defaultdict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        "SELECT case_id, item_id FROM assessment_items ORDER BY case_id, item_order"
    ):
        original_case_items[str(row["case_id"])].append(str(row["item_id"]))

    try:
        connection.execute("BEGIN IMMEDIATE")
        for proposal in proposals:
            parent_item_id = str(proposal["item_id"])
            case_id = str(proposal["case_id"])
            parent = connection.execute(
                "SELECT * FROM assessment_items WHERE item_id = ?",
                (parent_item_id,),
            ).fetchone()
            if parent is None:
                raise RuntimeError(f"proposal parent is missing: {parent_item_id}")
            affected_cases.add(case_id)
            connection.execute(
                "UPDATE assessment_items SET extraction_status = 'table_structure_review' "
                "WHERE item_id = ?",
                (parent_item_id,),
            )
            counts["parents_demoted"] += 1

            candidates = proposal.get("candidates")
            if not isinstance(candidates, list):
                raise RuntimeError(f"candidate list missing: {parent_item_id}")
            for candidate_order, candidate in enumerate(candidates, 1):
                if not isinstance(candidate, dict) or not bool(candidate.get("accepted")):
                    counts["rejected_candidates_retained_for_review"] += 1
                    continue
                title = str(candidate.get("title") or "").strip()
                key = title_key(title)
                if not key:
                    raise RuntimeError(f"empty candidate title: {parent_item_id}")
                if key in existing_titles[case_id]:
                    counts["duplicate_clean_sibling_skipped"] += 1
                    continue
                source_html = str(candidate.get("source_html") or "")
                if key not in title_key(element_text(lxml_html.fromstring(source_html))):
                    raise RuntimeError(f"candidate title not in source: {parent_item_id} {title}")
                item_id = item_identifier(parent_item_id, title, candidate_order)
                if connection.execute(
                    "SELECT 1 FROM assessment_items WHERE item_id = ?", (item_id,)
                ).fetchone():
                    raise RuntimeError(f"candidate item id collision: {item_id}")
                # Use the same conservative field extractor as the initial
                # detail build.  It keeps checkbox matrices and ambiguous
                # totals out of card metadata while the lossless source table
                # remains available to the teacher below.
                fields = _exact_fields(source_html)
                overview = str(fields["overview"])
                method = str(fields["method"])
                timing = str(fields["timing"])
                score = str(fields["score"])
                weight = str(fields["weight"])
                standards = list(fields["standards"])
                rubric_html = rubric_tables_from_source_html(source_html)
                temporary_order = 1_000_000 + counts["candidates_inserted"]
                connection.execute(
                    """
                    INSERT INTO assessment_items VALUES (
                        ?, ?, ?, ?, ?, 'table', 'bounded', ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        item_id,
                        case_id,
                        temporary_order,
                        title,
                        title,
                        int(parent["source_start"]),
                        int(parent["source_end"]),
                        overview,
                        method,
                        timing,
                        score,
                        weight,
                        json.dumps(standards, ensure_ascii=False, separators=(",", ":")),
                        zlib.compress(source_html.encode("utf-8"), level=9),
                        zlib.compress(rubric_html.encode("utf-8"), level=9),
                        len(source_html),
                        len(rubric_html),
                    ),
                )
                inserted_by_parent[parent_item_id].append(item_id)
                existing_titles[case_id].add(key)
                counts["candidates_inserted"] += 1

        # Keep clean source order.  Proposed children occupy the demoted
        # parent's position; review parents follow all public items.
        for case_id in affected_cases:
            ordered_public: list[str] = []
            ordered_review: list[str] = []
            for item_id in original_case_items[case_id]:
                if item_id in parent_ids:
                    ordered_public.extend(inserted_by_parent.get(item_id, []))
                    ordered_review.append(item_id)
                else:
                    ordered_public.append(item_id)
            final_order = [*ordered_public, *ordered_review]
            connection.execute(
                "UPDATE assessment_items SET item_order = item_order + 2000000 "
                "WHERE case_id = ?",
                (case_id,),
            )
            for item_order, item_id in enumerate(final_order, 1):
                connection.execute(
                    "UPDATE assessment_items SET item_order = ? WHERE item_id = ?",
                    (item_order, item_id),
                )

            title_rows = connection.execute(
                """
                SELECT title FROM assessment_items
                WHERE case_id = ? AND extraction_status = 'bounded'
                  AND title_basis IN ('table', 'heading')
                ORDER BY item_order
                """,
                (case_id,),
            ).fetchall()
            titles = [str(row[0]) for row in title_rows]
            status = "bounded" if titles else "bundle_review"
            connection.execute(
                """
                UPDATE case_detail_status
                SET extraction_status = ?, assessment_item_count = (
                        SELECT COUNT(*) FROM assessment_items WHERE case_id = ?
                    ),
                    detected_title_count = ?, detected_titles_json = ?
                WHERE case_id = ?
                """,
                (
                    status,
                    case_id,
                    len(titles),
                    json.dumps(titles, ensure_ascii=False, separators=(",", ":")),
                    case_id,
                ),
            )

        synchronize_summaries(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"candidate database integrity failed: {integrity}")
        counts["affected_cases"] = len(affected_cases)
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    args.output.unlink(missing_ok=True)
    temporary.replace(args.output)

    report = {
        "schema_version": 1,
        "source_database": str(args.database.resolve()),
        "candidate_database": str(args.output.resolve()),
        "counts": dict(sorted(counts.items())),
        "source_database_unchanged": True,
        "promotion_applied": False,
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
