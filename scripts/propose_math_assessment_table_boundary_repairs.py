"""Propose source-grounded assessment-item splits for whole-plan table bundles.

Only explicit ``평가 영역명`` cell values may become titles.  The script does
not mutate SQLite; it emits candidates and a residual queue so the proposal can
be audited before any database repair is applied.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import sqlite3
import unicodedata
import zlib
from collections import Counter
from pathlib import Path

from audit_math_assessment_table_structure import (
    HEADER_RE,
    WHOLE_PLAN_MARKERS,
    audit_html,
    compact,
    element_text,
    restore_escaped_table_rows,
)
from audit_math_assessment_titles_full import audit_flags, confidence
from lxml import etree
from lxml import html as lxml_html

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = (
    PROJECT_ROOT / "data" / "derived" / "math_assessment_table_structure_queue.csv"
)


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
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_table_boundary_repair_proposals.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_table_boundary_repair_report.json",
    )
    return parser.parse_args()


def review_item_ids(path: Path) -> set[str]:
    output: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            flags = set(str(row.get("flags") or "").split("|"))
            if "source:likely_unbounded_public_item" in flags:
                output.add(str(row.get("item_id") or ""))
    output.discard("")
    return output


def direct_rows(table: etree._Element) -> list[etree._Element]:
    return table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")


def explicit_area_title(row: etree._Element) -> str:
    cells = row.xpath("./th|./td")
    texts = [element_text(cell) for cell in cells]
    for index, text in enumerate(texts):
        if compact(text) != "평가영역명":
            continue
        for candidate in texts[index + 1 :]:
            clean = re.sub(r"\s+", " ", candidate).strip(" |:：")
            clean = re.split(
                r"\s+(?:(?:영역\s*)?만점|학기|평가\s*시기|반영\s*비율)(?:\s|$)",
                clean,
                maxsplit=1,
            )[0].strip(" |:：")
            if clean and not HEADER_RE.fullmatch(compact(clean)):
                return clean
    return ""


def table_fragments(table: etree._Element) -> list[tuple[str, str]]:
    rows = direct_rows(table)
    starts = [
        (index, explicit_area_title(row))
        for index, row in enumerate(rows)
        if explicit_area_title(row)
    ]
    if not starts:
        return [("", etree.tostring(table, encoding="unicode", method="html"))]
    output: list[tuple[str, str]] = []
    for position, (start, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(rows)
        fragment = copy.deepcopy(table)
        for node in direct_rows(fragment):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        body = fragment.find("tbody")
        if body is None:
            body = etree.SubElement(fragment, "tbody")
        for row in rows[start:end]:
            body.append(copy.deepcopy(row))
        output.append((title, etree.tostring(fragment, encoding="unicode", method="html")))
    return output


def is_policy_fragment(value: str) -> bool:
    visible = compact(element_text(lxml_html.fromstring(value)))
    marker_count = sum(compact(marker) in visible for marker in WHOLE_PLAN_MARKERS)
    return marker_count >= 2


def title_key(value: str) -> str:
    return re.sub(
        r"[^0-9A-Za-z가-힣ⅠⅡ]",
        "",
        unicodedata.normalize("NFKC", value),
    )


def split_candidates(value: str) -> list[dict[str, object]]:
    root = lxml_html.fromstring(f"<div>{value}</div>")
    tokens: list[tuple[str, str, bool]] = []
    for child in root:
        if child.tag.lower() == "table":
            for title, fragment in table_fragments(child):
                tokens.append((title, fragment, is_policy_fragment(fragment)))
        else:
            fragment = etree.tostring(child, encoding="unicode", method="html")
            tokens.append(("", fragment, is_policy_fragment(fragment)))

    grouped: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for title, fragment, policy in tokens:
        if title:
            current = {"title": title, "parts": [fragment]}
            grouped.append(current)
            continue
        if current is None:
            continue
        if policy:
            current = None
            continue
        parts = current["parts"]
        assert isinstance(parts, list)
        parts.append(fragment)

    combined: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for group in grouped:
        title = str(group["title"])
        key = title_key(title)
        if key not in combined:
            combined[key] = {"title": title, "parts": []}
            order.append(key)
        parts = combined[key]["parts"]
        assert isinstance(parts, list)
        parts.extend(group["parts"])

    candidates: list[dict[str, object]] = []
    for key in order:
        title = str(combined[key]["title"])
        parts = combined[key]["parts"]
        assert isinstance(parts, list)
        source_html = "\n".join(str(part) for part in parts)
        audit = audit_html(source_html)
        visible = compact(element_text(lxml_html.fromstring(f"<div>{source_html}</div>")))
        signals = {
            "has_title": compact(title) in visible,
            "has_assessment_structure": bool(
                re.search(r"수행과제|평가방법|평가요소|채점기준|성취기준|배점", visible)
            ),
            "single_area": "likely_unbounded_public_item" not in audit["flags"],
            "not_policy": not is_policy_fragment(source_html),
            "source_title_pattern": confidence(audit_flags(title, "table"), "table")
            != "reject",
            "single_course_prefix": "multiple_course_code_prefixes"
            not in audit["flags"],
        }
        accepted = all(signals.values())
        candidates.append(
            {
                "title": title,
                "accepted": accepted,
                "signals": signals,
                "source_html": source_html,
                "source_html_char_count": len(source_html),
                "table_count": int(audit["table_count"]),
                "flags": list(audit["flags"]),
            }
        )
    return candidates


def main() -> None:
    args = parse_args()
    target_ids = review_item_ids(args.queue)
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in target_ids)
    rows = connection.execute(
        f"""
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.source_start, item.source_end, item.source_html_zlib,
               cases.curriculum, cases.subject, cases.school_name,
               cases.region, cases.district
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.item_id IN ({placeholders})
        ORDER BY item.case_id, item.item_order
        """,
        sorted(target_ids),
    ).fetchall()
    connection.close()

    counts: Counter[str] = Counter()
    output_rows: list[dict[str, object]] = []
    for row in rows:
        source_html = restore_escaped_table_rows(
            zlib.decompress(bytes(row["source_html_zlib"])).decode("utf-8")
        )
        candidates = split_candidates(source_html)
        accepted = [candidate for candidate in candidates if candidate["accepted"]]
        if accepted:
            state = "split_proposed"
            if len(accepted) == len(candidates):
                counts["parents_fully_split"] += 1
            else:
                counts["parents_partially_split"] += 1
            counts["accepted_candidates"] += len(accepted)
            counts["rejected_candidates"] += len(candidates) - len(accepted)
        else:
            state = "residual_review"
            counts["residual_parents"] += 1
        counts["review_parents"] += 1
        output_rows.append(
            {
                "item_id": str(row["item_id"]),
                "case_id": str(row["case_id"]),
                "item_order": int(row["item_order"]),
                "curriculum": str(row["curriculum"]),
                "subject": str(row["subject"]),
                "school_name": str(row["school_name"]),
                "region": str(row["region"]),
                "district": str(row["district"]),
                "parent_title": str(row["title"]),
                "source_start": int(row["source_start"]),
                "source_end": int(row["source_end"]),
                "proposal_state": state,
                "candidates": candidates,
            }
        )

    if len(rows) != len(target_ids):
        raise SystemExit(
            f"review item coverage failed: requested={len(target_ids)} found={len(rows)}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    report = {
        "schema_version": 1,
        "database": str(args.database.resolve()),
        "proposal_jsonl": str(args.output.resolve()),
        "counts": dict(sorted(counts.items())),
        "mutation_applied": False,
        "policy": (
            "Candidates require an explicit source table assessment-area value, "
            "a visible assessment-structure marker, one remaining assessment area, "
            "and no whole-plan policy fragment."
        ),
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
