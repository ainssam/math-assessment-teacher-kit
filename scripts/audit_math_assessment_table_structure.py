"""Audit every public assessment item's reconstructed HTML table structure.

This audit is intentionally conservative.  It never rewrites source text or
guesses a missing cell.  Instead it identifies deterministic geometry defects,
page-split table fragments, and text that escaped a table so parser/renderer
repairs can be applied by failure class.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sqlite3
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from lxml import html as lxml_html

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_HTML_MODULE_PATH = (
    PROJECT_ROOT / "services" / "math-assessment-api" / "app" / "source_html.py"
)
SOURCE_HTML_SPEC = importlib.util.spec_from_file_location(
    "math_assessment_source_html", SOURCE_HTML_MODULE_PATH
)
if SOURCE_HTML_SPEC is None or SOURCE_HTML_SPEC.loader is None:
    raise RuntimeError(f"unable to load source HTML repairs: {SOURCE_HTML_MODULE_PATH}")
SOURCE_HTML_MODULE = importlib.util.module_from_spec(SOURCE_HTML_SPEC)
SOURCE_HTML_SPEC.loader.exec_module(SOURCE_HTML_MODULE)
restore_escaped_table_rows = SOURCE_HTML_MODULE.restore_escaped_table_rows


ACHIEVEMENT_CODE_RE = re.compile(
    r"\[\s*12\s*([A-Za-z가-힣ⅠⅡ]{1,16})\s*\d{2}\s*[-‐‑‒–—]?\s*\d{2}\s*\]"
)
HEADER_RE = re.compile(
    r"평가영역|수행과제|평가과제|과제명|성취기준|성취수준|평가방법|"
    r"평가시기|평가요소|채점기준|세부평가기준|수행수준|배점|총점"
)
STANDARDS_RE = re.compile(r"성취기준|성취수준|\[\s*12[A-Za-z가-힣ⅠⅡ]", re.I)
RUBRIC_RE = re.compile(r"평가요소|채점요소|채점기준|평가기준|수행수준|배점|점수")
PAGE_MARKER_RE = re.compile(r"^(?:-?\s*\d+\s*-?|\d+\s*/\s*\d+|쪽)$")
ASSESSMENT_AREA_LABEL_RE = re.compile(r"평가\s*영역\s*명")
TASK_LABEL_RE = re.compile(r"수행\s*과제")
WHOLE_PLAN_MARKERS = (
    "정의적 능력 평가",
    "평가 결과 분석 및 활용",
    "평가 방침",
    "결시생",
    "인정점",
    "학업성적관리규정",
)

SCREENSHOT_SIGNATURES = {
    "algebra_inquiry_rubric": "탐구 주제가 대수 과목과 연관성이 있는가",
    "algebra_orphan_standards": "지수함수와 로그함수의 그래프를 그릴 수 있고",
    "financial_math_split": "세금의 종류에 따라 세금을 계산할 수 있다",
}


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def positive_span(value: str | None) -> tuple[int, bool]:
    if value is None:
        return 1, True
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1, False
    if parsed < 1 or parsed > 200:
        return 1, False
    return parsed, True


def parse_fragment(value: str) -> etree._Element:
    parser = lxml_html.HTMLParser(recover=True, remove_comments=False)
    return lxml_html.fromstring(f"<div>{value}</div>", parser=parser)


def element_text(element: etree._Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part.strip())


def is_instruction_schedule(table: etree._Element) -> bool:
    row = table.find(".//tr")
    if row is None:
        return False
    cells = [compact(element_text(cell)) for cell in row.xpath("./th|./td")]
    if {"수업방법", "진도계획"}.issubset(cells):
        return True
    return bool(len(cells) >= 5 and re.fullmatch(r"\d{1,2}월", cells[0])
                and re.fullmatch(r"\d{1,2}\.\d{1,2}\.?[~∼～-]\d{1,2}\.\d{1,2}\.?", cells[1]))


@dataclass
class TableAudit:
    row_count: int
    cell_count: int
    widths: list[int]
    blank_cells: int
    invalid_spans: int
    overflowing_rowspans: int
    header_signal: bool
    standard_code_count: int
    standard_prefixes: set[str]
    standards_signal: bool
    rubric_signal: bool

    @property
    def modal_width(self) -> int:
        if not self.widths:
            return 0
        counts = Counter(self.widths)
        return counts.most_common(1)[0][0]

    @property
    def width_outlier_rows(self) -> int:
        mode = self.modal_width
        return sum(width != mode for width in self.widths)


def audit_table(table: etree._Element) -> TableAudit:
    rows = table.xpath(".//tr[not(ancestor::table[2])]")
    active_until: dict[int, int] = {}
    widths: list[int] = []
    blank_cells = 0
    cell_count = 0
    invalid_spans = 0
    overflowing_rowspans = 0

    for row_index, row in enumerate(rows):
        occupied = {column for column, end in active_until.items() if end > row_index}
        cells = row.xpath("./th|./td")
        column = 0
        for cell in cells:
            while column in occupied:
                column += 1
            rowspan, rowspan_valid = positive_span(cell.get("rowspan"))
            colspan, colspan_valid = positive_span(cell.get("colspan"))
            if not rowspan_valid or not colspan_valid:
                invalid_spans += 1
            if row_index + rowspan > len(rows):
                overflowing_rowspans += 1
                rowspan = max(1, len(rows) - row_index)
            for target_column in range(column, column + colspan):
                occupied.add(target_column)
                if rowspan > 1:
                    active_until[target_column] = row_index + rowspan
            if not compact(element_text(cell)):
                blank_cells += 1
            cell_count += 1
            column += colspan
        widths.append((max(occupied) + 1) if occupied else 0)

    text = element_text(table)
    prefixes = set(ACHIEVEMENT_CODE_RE.findall(text))
    code_count = len(ACHIEVEMENT_CODE_RE.findall(text))
    return TableAudit(
        row_count=len(rows),
        cell_count=cell_count,
        widths=widths,
        blank_cells=blank_cells,
        invalid_spans=invalid_spans,
        overflowing_rowspans=overflowing_rowspans,
        header_signal=bool(HEADER_RE.search(" ".join(element_text(row) for row in rows[:3]))),
        standard_code_count=code_count,
        standard_prefixes=prefixes,
        standards_signal=bool(STANDARDS_RE.search(text)),
        rubric_signal=bool(RUBRIC_RE.search(text)),
    )


def outside_table_text(root: etree._Element) -> str:
    nodes = root.xpath(".//text()[not(ancestor::table)]")
    return " ".join(str(node).strip() for node in nodes if str(node).strip())


def labeled_table_values(root: etree._Element, label_pattern: re.Pattern[str]) -> set[str]:
    """Return distinct source values immediately following an explicit row label."""

    values: set[str] = set()
    for row in root.xpath(".//tr"):
        cells = row.xpath("./th|./td")
        texts = [element_text(cell) for cell in cells]
        for index, text in enumerate(texts):
            if not label_pattern.fullmatch(compact(text)):
                continue
            for candidate in texts[index + 1 :]:
                normalized = compact(candidate)
                if normalized and not HEADER_RE.fullmatch(normalized):
                    values.add(normalized[:500])
                    break
    return values


def count_near_adjacent_compatible_tables(
    root: etree._Element, audits: list[TableAudit]
) -> int:
    """Count table pairs split only by whitespace, a page number, or a short label."""

    tables = root.xpath(".//table")
    index_by_id = {id(table): index for index, table in enumerate(tables)}
    count = 0
    for parent in root.iter():
        children = list(parent)
        for left_index, left in enumerate(children):
            if left.tag.lower() != "table":
                continue
            gap_parts: list[str] = []
            for right in children[left_index + 1 :]:
                if right.tag.lower() == "table":
                    left_audit = audits[index_by_id[id(left)]]
                    right_audit = audits[index_by_id[id(right)]]
                    gap = compact(" ".join(gap_parts))
                    gap_is_safe = not gap or len(gap) <= 24 or bool(PAGE_MARKER_RE.match(gap))
                    widths_match = (
                        left_audit.modal_width > 0
                        and left_audit.modal_width == right_audit.modal_width
                    )
                    same_kind = (
                        left_audit.standards_signal == right_audit.standards_signal
                        or left_audit.rubric_signal == right_audit.rubric_signal
                    )
                    if gap_is_safe and widths_match and same_kind:
                        count += 1
                    break
                gap_parts.append(element_text(right))
                if len(compact(" ".join(gap_parts))) > 80:
                    break
    return count


def row_grade(row: etree._Element) -> str:
    grades = [
        compact(element_text(cell))
        for cell in row.xpath("./th|./td")
        if compact(element_text(cell)) in {"A", "B", "C", "D", "E"}
    ]
    return grades[0] if len(grades) == 1 else ""


def count_achievement_level_page_breaks(root: etree._Element) -> int:
    count = 0
    for parent in root.iter():
        children = list(parent)
        for index, table in enumerate(children[:-1]):
            next_table = children[index + 1]
            if table.tag.lower() != "table" or next_table.tag.lower() != "table":
                continue
            left_rows = table.xpath(".//tr[not(ancestor::table[2])]")
            right_rows = next_table.xpath(".//tr[not(ancestor::table[2])]")
            if len(left_rows) < 3 or len(right_rows) < 2:
                continue
            if "".join(row_grade(row) for row in left_rows[-3:]) != "ABC":
                continue
            if "".join(row_grade(row) for row in right_rows[:2]) != "DE":
                continue
            evidence = compact(f"{element_text(table)} {element_text(next_table)}")
            if re.search(r"성취기준|성취수준|수준진술문|\[(?:10|12)", evidence):
                count += 1
    return count


def count_section_local_blank_column_tables(root: etree._Element) -> int:
    count = 0
    for table in root.xpath(".//table"):
        rows = table.xpath(".//tr[not(ancestor::table[2])]")
        if len(rows) < 5:
            continue
        row_columns: list[tuple[int, int]] = []
        for row in rows:
            width = 0
            last_content_column = 0
            for cell in row.xpath("./th|./td"):
                colspan, _ = positive_span(cell.get("colspan"))
                width += colspan
                if compact(element_text(cell)):
                    last_content_column = width
            row_columns.append((width, last_content_column))
        full_width = max((width for width, _ in row_columns), default=0)
        leading_sparse = any(
            full_width - last_content >= 2
            for _, last_content in row_columns[:2]
        )
        visible = compact(element_text(table))
        if (
            full_width >= 4
            and leading_sparse
            and "성취기준" in visible
            and re.search(r"평가시기|평가방법|평가요소|채점기준", visible)
        ):
            count += 1
    return count


def audit_html(value: str, *, is_rubric: bool = False) -> dict[str, object]:
    flags: set[str] = set()
    try:
        root = parse_fragment(value)
    except (etree.ParserError, ValueError):
        return {
            "flags": ["html_parse_failed"],
            "table_count": 0,
            "row_count": 0,
            "char_count": len(value),
        }

    tables = root.xpath(".//table")
    if is_rubric and any(is_instruction_schedule(table) for table in tables):
        flags.add("instruction_schedule_in_rubric")
    audits = [audit_table(table) for table in tables]
    visible = element_text(root)
    outside = outside_table_text(root)
    outside_codes = ACHIEVEMENT_CODE_RE.findall(outside)
    all_prefixes = set(ACHIEVEMENT_CODE_RE.findall(visible))
    area_label_count = len(ASSESSMENT_AREA_LABEL_RE.findall(visible))
    task_label_count = len(TASK_LABEL_RE.findall(visible))
    area_values = labeled_table_values(root, re.compile(r"평가영역명"))
    compact_visible = compact(visible)
    whole_plan_marker_count = sum(
        compact(marker) in compact_visible for marker in WHOLE_PLAN_MARKERS
    )

    if len(value) > 250_000:
        flags.add("oversized_html")
    if len(tables) > 24:
        flags.add("excessive_table_count")
    if len(all_prefixes) >= 3:
        flags.add("multiple_course_code_prefixes")
    if len(outside_codes) >= 2:
        flags.add("orphan_achievement_codes")
    if len(outside_codes) >= 6:
        flags.add("many_orphan_achievement_codes")
    if area_label_count >= 2:
        flags.add("multiple_assessment_area_labels")
    if len(area_values) >= 2:
        flags.add("multiple_distinct_assessment_areas")
    if task_label_count >= 2:
        flags.add("multiple_performance_task_labels")
    if whole_plan_marker_count >= 2 and len(tables) >= 6:
        flags.add("whole_plan_policy_leak")
    if (
        len(area_values) >= 2
        or (whole_plan_marker_count >= 2 and len(tables) >= 6)
    ):
        flags.add("likely_unbounded_public_item")

    standards_tables = sum(audit.standards_signal for audit in audits)
    if standards_tables >= 3:
        flags.add("split_standards_tables")
    if standards_tables >= 8:
        flags.add("many_split_standards_tables")

    adjacent = count_near_adjacent_compatible_tables(root, audits)
    if adjacent:
        flags.add("adjacent_compatible_table_fragments")
    achievement_level_page_breaks = count_achievement_level_page_breaks(root)
    if achievement_level_page_breaks:
        flags.add("achievement_level_page_break")
    section_local_blank_column_tables = count_section_local_blank_column_tables(root)
    if section_local_blank_column_tables:
        flags.add("section_local_trailing_blank_columns")

    for audit in audits:
        if audit.invalid_spans:
            flags.add("invalid_span_value")
        if audit.overflowing_rowspans:
            flags.add("rowspan_overflows_table")
        if (
            audit.row_count >= 4
            and audit.width_outlier_rows >= 2
            and audit.width_outlier_rows / audit.row_count >= 0.2
        ):
            flags.add("inconsistent_effective_columns")
        if (
            audit.cell_count >= 12
            and audit.blank_cells / max(audit.cell_count, 1) >= 0.45
        ):
            flags.add("high_blank_cell_ratio")
        if audit.row_count >= 6 and not audit.header_signal:
            flags.add("large_table_without_header_signal")
        if audit.modal_width >= 14:
            flags.add("very_wide_table")

    signatures = [
        name for name, signature in SCREENSHOT_SIGNATURES.items()
        if compact(signature) in compact(visible)
    ]
    return {
        "flags": sorted(flags),
        "table_count": len(tables),
        "row_count": sum(audit.row_count for audit in audits),
        "char_count": len(value),
        "outside_achievement_code_count": len(outside_codes),
        "assessment_area_label_count": area_label_count,
        "distinct_assessment_area_count": len(area_values),
        "performance_task_label_count": task_label_count,
        "whole_plan_marker_count": whole_plan_marker_count,
        "course_code_prefix_count": len(all_prefixes),
        "course_code_prefixes": sorted(all_prefixes),
        "standards_table_count": standards_tables,
        "adjacent_compatible_table_pairs": adjacent,
        "achievement_level_page_break_pairs": achievement_level_page_breaks,
        "section_local_blank_column_tables": section_local_blank_column_tables,
        "max_effective_columns": max((max(audit.widths, default=0) for audit in audits), default=0),
        "width_outlier_rows": sum(audit.width_outlier_rows for audit in audits),
        "blank_cell_count": sum(audit.blank_cells for audit in audits),
        "invalid_span_count": sum(audit.invalid_spans for audit in audits),
        "overflowing_rowspan_count": sum(audit.overflowing_rowspans for audit in audits),
        "matched_screenshot_signatures": signatures,
    }


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
        default=root / "data" / "derived" / "math_assessment_table_structure_audit.json",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_table_structure_queue.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.source_html_zlib, item.rubric_html_zlib,
               cases.curriculum, cases.subject, cases.school_name,
               cases.region, cases.district
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
          AND item.title_basis IN ('table', 'heading')
        ORDER BY item.case_id, item.item_order
        """
    ).fetchall()
    connection.close()

    queue: list[dict[str, object]] = []
    flag_counts: Counter[str] = Counter()
    item_flag_counts: Counter[str] = Counter()
    signature_matches: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    totals = Counter()

    for index, row in enumerate(rows, 1):
        item_flags: set[str] = set()
        part_results: dict[str, dict[str, object]] = {}
        for part_name, blob_name in (
            ("source", "source_html_zlib"),
            ("rubric", "rubric_html_zlib"),
        ):
            try:
                value = restore_escaped_table_rows(
                    zlib.decompress(bytes(row[blob_name])).decode("utf-8")
                )
                result = audit_html(value, is_rubric=part_name == "rubric")
            except (zlib.error, UnicodeDecodeError):
                result = {
                    "flags": ["html_decode_failed"],
                    "table_count": 0,
                    "row_count": 0,
                    "char_count": 0,
                }
            part_results[part_name] = result
            part_flags = set(result["flags"])
            item_flags.update(f"{part_name}:{flag}" for flag in part_flags)
            for flag in part_flags:
                flag_counts[f"{part_name}:{flag}"] += 1
            for signature in result.get("matched_screenshot_signatures", []):
                if len(signature_matches[str(signature)]) < 20:
                    signature_matches[str(signature)].append(
                        {
                            "item_id": str(row["item_id"]),
                            "case_id": str(row["case_id"]),
                            "school_name": str(row["school_name"]),
                            "subject": str(row["subject"]),
                            "title": str(row["title"]),
                            "part": part_name,
                        }
                    )

        if item_flags:
            item_flag_counts["items_with_any_flag"] += 1
            queue.append(
                {
                    "item_id": str(row["item_id"]),
                    "case_id": str(row["case_id"]),
                    "item_order": int(row["item_order"]),
                    "curriculum": str(row["curriculum"]),
                    "subject": str(row["subject"]),
                    "school_name": str(row["school_name"]),
                    "region": str(row["region"]),
                    "district": str(row["district"]),
                    "title": str(row["title"]),
                    "flags": "|".join(sorted(item_flags)),
                    "source_table_count": part_results["source"]["table_count"],
                    "source_row_count": part_results["source"]["row_count"],
                    "source_char_count": part_results["source"]["char_count"],
                    "source_orphan_codes": part_results["source"].get(
                        "outside_achievement_code_count", 0
                    ),
                    "source_assessment_area_labels": part_results["source"].get(
                        "assessment_area_label_count", 0
                    ),
                    "source_distinct_assessment_areas": part_results["source"].get(
                        "distinct_assessment_area_count", 0
                    ),
                    "source_performance_task_labels": part_results["source"].get(
                        "performance_task_label_count", 0
                    ),
                    "source_whole_plan_markers": part_results["source"].get(
                        "whole_plan_marker_count", 0
                    ),
                    "source_standards_tables": part_results["source"].get(
                        "standards_table_count", 0
                    ),
                    "source_column_outliers": part_results["source"].get(
                        "width_outlier_rows", 0
                    ),
                    "rubric_table_count": part_results["rubric"]["table_count"],
                    "rubric_row_count": part_results["rubric"]["row_count"],
                    "rubric_char_count": part_results["rubric"]["char_count"],
                    "rubric_column_outliers": part_results["rubric"].get(
                        "width_outlier_rows", 0
                    ),
                }
            )
        totals["source_tables"] += int(part_results["source"]["table_count"])
        totals["rubric_tables"] += int(part_results["rubric"]["table_count"])
        if index % 2000 == 0:
            print(f"audited {index}/{len(rows)}", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "database": str(args.database.resolve()),
        "public_item_count": len(rows),
        "items_with_any_flag": item_flag_counts["items_with_any_flag"],
        "flag_counts": dict(sorted(flag_counts.items())),
        "totals": dict(sorted(totals.items())),
        "screenshot_signature_matches": dict(sorted(signature_matches.items())),
        "queue": str(args.queue.resolve()),
        "audit_policy": (
            "Deterministic structural screening only. Flags do not authorize text deletion "
            "or inferred cell reconstruction; source-boundary and ambiguous fragment repairs "
            "still require source-grounded review."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fieldnames = list(queue[0]) if queue else ["item_id", "flags"]
    with args.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(queue)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
