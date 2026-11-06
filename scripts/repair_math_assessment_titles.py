"""Repair assessment names against the already preserved source HTML.

This is intentionally narrower than the full detail repair.  It never rewrites
source or rubric HTML.  It demotes unit/standards headings, prefers explicit
assessment-name table cells, and preserves the source-table title list from
the audited base catalogue when a detail boundary remains uncertain.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zlib
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_titles_full import (
    audit_flags,
    confidence,
)
from scripts.build_math_assessment_detail_db import synchronize_case_summaries
from scripts.build_math_assessment_publish_db import (
    TASK_SIGNAL_RE,
    compact_label,
    html_tables,
    normalize_task_name,
    task_name_is_rejected,
)
from scripts.math_assessment_detail_parser import (
    PERFORMANCE_MARKER_RE,
    _clean_heading_title,
    compact_text,
    explicit_segment_title,
    heading_title_is_structural,
    visible_text,
)

SYNTHETIC_BUNDLE_TITLE = "수행평가 원문 구간"
GENERIC_TITLES = {"구체적 과제명 미탐지", SYNTHETIC_BUNDLE_TITLE}
DIRECT_TITLE_LABELS = {
    "수행평가명",
    "평가명",
    "수행평가영역",
    "수행평가과제명",
    "평가과제명",
    "평가영역명",
    "수행과제",
    "수행과제명",
    "과제명",
}
SUPPORT_FIELD_LABELS = {
    "평가내용",
    "반영비율",
    "평가기준",
    "배점",
    "평가방법",
    "성취기준",
    "만점",
    "평가만점",
    "결시자처리기준",
    "성적처리우선순위",
    "평가시기",
    "시기",
}
NON_MATH_SOURCE_SIGNAL_RE = re.compile(
    r"기본권|시민의\s*복지|사회적\s*연대|타인의\s*고통|"
    r"사회문제\s*주제\s*탐구|민주주의\s*방식|다문화\s*사회"
)
MATH_SOURCE_SIGNAL_RE = re.compile(
    r"수학|함수|방정식|부등식|수열|미분|적분|확률|통계|기하|"
    r"도형|벡터|행렬|지수|로그|삼각"
)


def source_is_non_math_leak(subject: str, source_text: str) -> bool:
    """Flag clearly non-mathematical source sections inside a math case bundle."""

    return bool(
        subject not in {"경제 수학", "수학과 문화"}
        and NON_MATH_SOURCE_SIGNAL_RE.search(source_text)
        and not MATH_SOURCE_SIGNAL_RE.search(source_text)
    )


def source_aligned_catalog_spelling(title: str, candidates: list[str]) -> str:
    """Restore audited spacing only when source and catalogue identities match."""

    title_key = compact_text(title)
    if not title_key:
        return title
    for candidate in candidates:
        spelling = re.sub(r"\s+", " ", str(candidate)).strip()
        if (
            spelling
            and spelling != title
            and compact_text(spelling) == title_key
            and credible_title(spelling)
        ):
            return spelling
    return title


class TopLevelTableParser(HTMLParser):
    """Read only outer table cells so nested rubric rows cannot become titles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
            return
        if self.depth != 1:
            return
        if tag == "tr":
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []
            values = {key.lower(): value for key, value in attrs}
            try:
                self.colspan = max(1, min(int(values.get("colspan") or "1"), 50))
            except ValueError:
                self.colspan = 1

    def handle_data(self, data: str) -> None:
        if self.depth == 1 and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.depth == 1 and tag in {"th", "td"} and self.cell is not None:
            value = re.sub(r"\s+", " ", " ".join(self.cell)).strip()
            if self.row is not None:
                self.row.extend([value] * self.colspan)
            self.cell = None
            self.colspan = 1
        elif self.depth == 1 and tag == "tr":
            if self.table is not None and self.row:
                self.table.append(self.row)
            self.row = None
        if tag == "table" and self.depth:
            if self.depth == 1 and self.table:
                self.tables.append(self.table)
                self.table = None
            self.depth -= 1


def top_level_tables(source_html: str) -> list[list[list[str]]]:
    parser = TopLevelTableParser()
    parser.feed(source_html)
    parser.close()
    return parser.tables


def credible_title(title: str) -> bool:
    clean = visible_text(title).strip()
    return bool(
        clean
        and 2 <= len(compact_text(clean)) <= 60
        and clean not in GENERIC_TITLES
        and not heading_title_is_structural(clean)
        and not re.search(r"[.。]$", clean)
    )


def deduplicate_titles(titles: list[str]) -> list[str]:
    """Preserve source order while publishing each detected name only once."""

    return list(dict.fromkeys(titles))


def task_identity(title: str) -> str:
    """Match duplicate summary/detail names without changing source display."""

    without_method = re.sub(
        r"\s*[\[(](?:서[·ㆍ‧]?논술형|서술형|논술형|포트폴리오|프로젝트)[])]\s*$",
        "",
        title,
    )
    return compact_text(without_method)


def strict_source_titles(source_html: str) -> list[str]:
    """Extract titles only from explicit labels or assessment-summary columns."""

    titles: list[str] = []

    def source_cell_spelling(normalized_name: str, fallback: str) -> str:
        """Use the original cell spelling when normalisation changed only spacing."""

        key = compact_label(normalized_name)
        for match in re.finditer(
            r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", source_html, re.I | re.S
        ):
            candidate = re.sub(r"\s+", " ", visible_text(match.group(1))).strip(
                " |#*★☆:-▪∙•·○◦ㅇᄋ"
            )
            if candidate and compact_label(candidate) == key:
                return candidate
        return fallback

    def add(raw: str, *, require_task_signal: bool = True) -> None:
        name = normalize_task_name(raw)
        source_spelling = re.sub(r"\s+", " ", str(raw)).strip(" |#*★☆:-▪∙•·○◦ㅇᄋ")
        title_status = confidence(
            audit_flags(name, "table"),
            "table",
            explicit_source_label=True,
        )
        if (
            not credible_title(name)
            or task_name_is_rejected(name)
            or title_status != "supported"
            or (require_task_signal and not TASK_SIGNAL_RE.search(name))
            or any(compact_label(existing) == compact_label(name) for existing in titles)
        ):
            return
        # Normalisation is used only as a safety check.  If the source cell
        # already says the same thing, retain its spacing and punctuation so
        # the bundle notice is a source transcription rather than a rewrite.
        display_name = (
            source_spelling
            if compact_label(source_spelling) == compact_label(name)
            else name
        )
        display_name = source_cell_spelling(name, display_name)
        if display_name not in titles:
            titles.append(display_name)

    for match in re.finditer(
        r"(?:수행\s*평가\s*명|평가\s*과제\s*명|평가\s*영역\s*명)"
        r"\s*[:：]\s*([^<\r\n]{2,120})(?=<|$)",
        source_html,
        re.I,
    ):
        add(match.group(1), require_task_signal=False)

    for rows in top_level_tables(source_html):
        for row in rows:
            labels = [compact_label(cell) for cell in row]
            for index, label in enumerate(labels[:-1]):
                if label not in DIRECT_TITLE_LABELS:
                    continue
                for candidate in row[index + 1 :]:
                    if compact_label(candidate) in SUPPORT_FIELD_LABELS:
                        break
                    add(candidate, require_task_signal=False)

        for header_index, row in enumerate(rows):
            labels = [compact_label(cell) for cell in row]
            support_count = sum(label in SUPPORT_FIELD_LABELS for label in labels)
            if support_count < 2:
                continue
            for column, label in enumerate(labels):
                if label not in {"영역", "평가영역", "수행평가영역"}:
                    continue
                for candidate_row in rows[header_index + 1 :]:
                    if column < len(candidate_row):
                        add(candidate_row[column])

    for rows in html_tables(source_html):
        performance_columns: set[int] = set()
        for row in rows:
            labels = [compact_label(cell) for cell in row]
            if labels and labels[0].startswith(("평가종류", "평가유형")):
                performance_columns.update(
                    index for index, label in enumerate(labels) if label == "수행평가"
                )
        if not performance_columns:
            continue
        for row in rows:
            if not row:
                continue
            row_label = compact_label(row[0])
            is_area_row = row_label.startswith("영역") or row_label in {
                "횟수영역",
                "평가영역",
                "수행평가영역",
            }
            if not is_area_row:
                continue
            for column in sorted(performance_columns):
                if column < len(row):
                    add(row[column])
    return titles


def repair_titles(
    connection: sqlite3.Connection,
    base_titles: dict[str, tuple[str, str, list[str]]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    bounded = connection.execute(
        """
        SELECT item.item_id, item.title, item.title_raw, item.title_basis,
               item.source_html_zlib, cases.subject
        FROM assessment_items item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
        ORDER BY item.item_id
        """
    ).fetchall()
    for (
        item_id,
        original_title,
        original_title_raw,
        original_title_basis,
        source_blob,
        subject,
    ) in bounded:
        source_html = zlib.decompress(source_blob).decode("utf-8")
        source_text = visible_text(source_html)
        table_title = explicit_segment_title(source_html)
        display_table_title = (
            _clean_heading_title(table_title)[0] if table_title else ""
        )
        table_flags = audit_flags(str(display_table_title or ""), "table")
        table_status = confidence(
            table_flags,
            "table",
            explicit_source_label=True,
        )
        table_title_is_confirmed = bool(
            table_title
            and credible_title(display_table_title)
            and table_status == "supported"
        )
        if table_title_is_confirmed:
            connection.execute(
                """
                UPDATE assessment_items
                SET title = ?, title_raw = ?, title_basis = 'table'
                WHERE item_id = ?
                """,
                (display_table_title, table_title, str(item_id)),
            )
            if (
                display_table_title != str(original_title)
                or table_title != str(original_title_raw)
                or str(original_title_basis) != "table"
            ):
                counts["titles_replaced_from_explicit_table_label"] += 1
            original_title = display_table_title
            original_title_raw = table_title
            original_title_basis = "table"
        else:
            repaired_heading, _ = _clean_heading_title(str(original_title_raw))
            if repaired_heading != str(original_title) and credible_title(repaired_heading):
                connection.execute(
                    """
                    UPDATE assessment_items
                    SET title = ?, title_basis = 'heading'
                    WHERE item_id = ?
                    """,
                    (repaired_heading, str(item_id)),
                )
                original_title = repaired_heading
                original_title_basis = "heading"
                counts["titles_cleaned_from_collapsed_structural_heading"] += 1
        title_flags = audit_flags(str(original_title), str(original_title_basis))
        title_status = confidence(title_flags, str(original_title_basis))
        source_table_confirmed = table_title_is_confirmed
        if title_status != "supported" and str(original_title_basis) == "table":
            source_title_keys = {
                compact_text(source_title)
                for source_title in strict_source_titles(source_html)
            }
            source_table_confirmed = (
                source_table_confirmed
                or compact_text(str(original_title)) in source_title_keys
            )
            title_status = confidence(
                title_flags,
                str(original_title_basis),
                explicit_source_label=source_table_confirmed,
            )
        non_math_source_leak = source_is_non_math_leak(str(subject), source_text)
        if (
            heading_title_is_structural(str(original_title))
            or not credible_title(str(original_title))
            or not PERFORMANCE_MARKER_RE.search(source_text)
            or title_status != "supported"
            or non_math_source_leak
        ):
            connection.execute(
                """
                UPDATE assessment_items
                SET extraction_status = 'bundle_review'
                WHERE item_id = ?
                """,
                (str(item_id),),
            )
            if heading_title_is_structural(str(original_title)):
                key = "structural_headings_demoted_to_review_bundle"
            elif non_math_source_leak:
                key = "non_math_source_sections_demoted_to_review_bundle"
            elif title_status != "supported":
                key = f"strict_{title_status}_titles_demoted_to_review_bundle"
            else:
                key = "unit_or_standard_headings_demoted_to_review_bundle"
            counts[key] += 1

    cases = connection.execute("SELECT case_id FROM case_detail_status ORDER BY case_id").fetchall()
    for (case_id,) in cases:
        base_title, _base_basis, base_candidates = base_titles.get(
            str(case_id),
            ("", "", []),
        )
        audited_spellings = deduplicate_titles([base_title, *base_candidates])
        for item_id, item_title in connection.execute(
            """
            SELECT item_id, title FROM assessment_items
            WHERE case_id = ? AND extraction_status = 'bounded'
            """,
            (case_id,),
        ).fetchall():
            restored_title = source_aligned_catalog_spelling(
                str(item_title),
                audited_spellings,
            )
            if restored_title != str(item_title):
                connection.execute(
                    "UPDATE assessment_items SET title = ? WHERE item_id = ?",
                    (restored_title, str(item_id)),
                )
                counts["titles_spacing_restored_from_audited_catalog"] += 1
        bounded_items = connection.execute(
            """
            SELECT item_id, title, title_basis, source_html_char_count,
                   rubric_html_char_count, item_order
            FROM assessment_items
            WHERE case_id = ? AND extraction_status = 'bounded'
            ORDER BY item_order
            """,
            (case_id,),
        ).fetchall()
        groups: dict[str, list[tuple[object, ...]]] = {}
        for item in bounded_items:
            groups.setdefault(task_identity(str(item[1])), []).append(item)
        duplicate_ids: list[str] = []
        for duplicate_group in groups.values():
            if len(duplicate_group) < 2:
                continue
            keep = max(
                duplicate_group,
                key=lambda item: (
                    int(item[3]) + int(item[4]),
                    str(item[2]) == "heading",
                    -int(item[5]),
                ),
            )
            duplicate_ids.extend(
                str(item[0]) for item in duplicate_group if item[0] != keep[0]
            )
        if duplicate_ids:
            placeholders = ",".join("?" for _ in duplicate_ids)
            connection.execute(
                f"""
                UPDATE assessment_items SET extraction_status = 'bundle_review'
                WHERE item_id IN ({placeholders})
                """,
                duplicate_ids,
            )
            counts["duplicate_summary_or_detail_items_demoted"] += len(duplicate_ids)

        heading_intervals = connection.execute(
            """
            SELECT source_start, source_end FROM assessment_items
            WHERE case_id = ? AND extraction_status = 'bounded'
              AND title_basis = 'heading'
            """,
            (case_id,),
        ).fetchall()
        if heading_intervals:
            overlapping_table_ids = [
                str(item_id)
                for item_id, source_start, source_end in connection.execute(
                    """
                    SELECT item_id, source_start, source_end FROM assessment_items
                    WHERE case_id = ? AND extraction_status = 'bounded'
                      AND title_basis = 'table'
                    """,
                    (case_id,),
                ).fetchall()
                if any(
                    int(source_start) < int(heading_end)
                    and int(source_end) > int(heading_start)
                    for heading_start, heading_end in heading_intervals
                )
            ]
            if overlapping_table_ids:
                placeholders = ",".join("?" for _ in overlapping_table_ids)
                connection.execute(
                    f"""
                    UPDATE assessment_items SET extraction_status = 'bundle_review'
                    WHERE item_id IN ({placeholders})
                    """,
                    overlapping_table_ids,
                )
                counts["overlapping_table_subrows_demoted_below_heading"] += (
                    len(overlapping_table_ids)
                )
        items = connection.execute(
            """
            SELECT title, title_basis, extraction_status, source_html_zlib
            FROM assessment_items WHERE case_id = ? ORDER BY item_order
            """,
            (case_id,),
        ).fetchall()
        detected = deduplicate_titles(
            [
                str(item[0])
                for item in items
                if str(item[2]) == "bounded" and str(item[1]) in {"table", "heading"}
            ]
        )
        case_status = "bounded" if detected else "bundle_review"
        if not detected and items:
            base_title, base_basis, _base_candidates = base_titles.get(
                str(case_id),
                ("", "", []),
            )
            if base_basis == "table" and credible_title(base_title):
                detected = [base_title]
                counts["bundle_cases_preserving_audited_primary_table_title"] += 1
            source_html = "\n".join(zlib.decompress(item[3]).decode("utf-8") for item in items)
            for title in strict_source_titles(source_html):
                if title not in detected:
                    detected.append(title)
                    counts["bundle_titles_added_from_strict_source_structure"] += 1
            if detected:
                counts["bundle_cases_with_strict_or_audited_titles"] += 1
        connection.execute(
            """
            UPDATE case_detail_status
            SET extraction_status = ?, detected_title_count = ?, detected_titles_json = ?
            WHERE case_id = ?
            """,
            (
                case_status,
                len(detected),
                json.dumps(detected, ensure_ascii=False, separators=(",", ":")),
                str(case_id),
            ),
        )
    synchronize_case_summaries(connection)
    return dict(sorted(counts.items()))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--base-db",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_title_repair_manifest.json",
    )
    args = parser.parse_args()
    with sqlite3.connect(args.base_db) as base_connection:
        base_titles = {
            str(case_id): (
                str(primary_task_name).strip(),
                str(basis).strip(),
                [
                    str(candidate).strip()
                    for candidate in json.loads(str(task_names_json or "[]"))
                    if str(candidate).strip()
                ],
            )
            for case_id, primary_task_name, basis, task_names_json in base_connection.execute(
                "SELECT case_id, primary_task_name, title_basis, task_names_json FROM cases"
            )
        }

    descriptor, temp_name = tempfile.mkstemp(
        prefix=args.database.stem + "_title_repair_",
        suffix=".partial",
        dir=args.database.parent,
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    shutil.copy2(args.database, temporary)
    started = dt.datetime.now(dt.UTC)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = NORMAL")
            counts = repair_titles(connection, base_titles)
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"SQLite integrity check failed: {integrity}")
        try:
            os.replace(temporary, args.database)
        except PermissionError:
            with (
                sqlite3.connect(temporary) as source,
                sqlite3.connect(args.database) as destination,
            ):
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                print(f"title_repair_completed_checkpoint_retained={temporary}")
    except BaseException:
        print(f"title_repair_checkpoint={temporary}", flush=True)
        raise

    completed = dt.datetime.now(dt.UTC)
    manifest = {
        "schema_version": 1,
        "generated_at": completed.isoformat(timespec="seconds"),
        "elapsed_seconds": round((completed - started).total_seconds(), 3),
        "database": {
            "path": str(args.database.resolve()),
            "bytes": args.database.stat().st_size,
            "sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        },
        "counts": counts,
    }
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
