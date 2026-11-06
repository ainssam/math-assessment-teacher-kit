"""Build the lossless, item-level assessment detail layer.

The script streams the already verified full-document extraction once, keeps
only the 8,800 catalogue source hashes, and stores each source-bounded
performance assessment as compressed safe HTML.  Originals are never changed.
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
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_math_assessment_publish_db import assessment_category, case_identifier
from scripts.math_assessment_detail_parser import (
    ParsedAssessmentItem,
    parse_assessment_section,
    visible_text,
)

SCHEMA_SQL = """
CREATE TABLE case_detail_status (
    case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
    source_format TEXT NOT NULL,
    boundary_status TEXT NOT NULL,
    extraction_status TEXT NOT NULL,
    assessment_item_count INTEGER NOT NULL CHECK (assessment_item_count >= 1),
    detected_title_count INTEGER NOT NULL CHECK (detected_title_count >= 0),
    detected_titles_json TEXT NOT NULL,
    source_section_char_count INTEGER NOT NULL CHECK (source_section_char_count >= 0),
    full_text_sha256 TEXT NOT NULL,
    context_jump_count INTEGER NOT NULL CHECK (context_jump_count = 0)
) WITHOUT ROWID;

CREATE TABLE assessment_items (
    item_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    item_order INTEGER NOT NULL CHECK (item_order >= 1),
    title TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    extraction_status TEXT NOT NULL,
    source_start INTEGER NOT NULL CHECK (source_start >= 0),
    source_end INTEGER NOT NULL CHECK (source_end >= source_start),
    overview TEXT NOT NULL,
    method TEXT NOT NULL,
    timing TEXT NOT NULL,
    score TEXT NOT NULL,
    weight TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    source_html_zlib BLOB NOT NULL,
    rubric_html_zlib BLOB NOT NULL,
    source_html_char_count INTEGER NOT NULL CHECK (source_html_char_count >= 0),
    rubric_html_char_count INTEGER NOT NULL CHECK (rubric_html_char_count >= 0),
    UNIQUE (case_id, item_order)
);

CREATE INDEX idx_assessment_items_case_order
ON assessment_items(case_id, item_order);

CREATE INDEX idx_assessment_items_title
ON assessment_items(title);
"""


def read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"malformed JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"JSON object required {path}:{line_number}")
            yield row


SOURCE_SHA_BYTES_RE = re.compile(rb'"sha256"\s*:\s*"([0-9a-f]{64})"')


def read_target_source_jsonl(
    path: Path, target_hashes: set[str]
) -> Iterable[tuple[int, dict[str, object]]]:
    """Avoid decoding multi-megabyte text fields for non-catalogue sources."""

    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            match = SOURCE_SHA_BYTES_RE.search(line[:16384])
            if not match or match.group(1).decode("ascii") not in target_hashes:
                continue
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SystemExit(f"malformed target JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"JSON object required {path}:{line_number}")
            yield line_number, row


def item_identifier(case_id: str, order: int, source_start: int, title: str) -> str:
    payload = f"{case_id}|{order}|{source_start}|{title}".encode()
    return hashlib.sha256(payload).hexdigest()[:28]


def compressed_html(value: str) -> bytes:
    return zlib.compress(value.encode("utf-8"), level=9)


def source_format(source: dict[str, object]) -> str:
    candidate = str(source.get("candidate_name") or "")
    suffix = Path(candidate).suffix.lower().lstrip(".")
    return suffix or "unknown"


def compact_catalog_row(row: dict[str, object]) -> dict[str, object]:
    source = row.get("source")
    if not isinstance(source, dict):
        source = {}
    source_sha = str(row.get("sha256") or "")
    curriculum = str(row.get("resolved_curriculum") or "shared")
    subject = str(row.get("subject") or "").strip()
    if not source_sha or not subject:
        raise SystemExit("catalog row missing source hash or subject")
    return {
        "case_id": case_identifier(source_sha, curriculum, subject),
        "sha256": source_sha,
        "subject": subject,
        "source_format": source_format(source),
        "task_name_candidates": tuple(
            str(value).strip()
            for value in row.get("task_name_candidates", [])
            if str(value).strip()
        ),
    }


def update_case_summary(
    connection: sqlite3.Connection,
    case_id: str,
    detected_titles: tuple[str, ...],
    first_item: ParsedAssessmentItem,
) -> None:
    # Do not erase the base catalogue's source-table title with a synthetic
    # bundle label.  The final synchronization step keeps that title only when
    # it is visible again inside the subject-local source HTML.
    if not detected_titles and first_item.extraction_status != "bounded":
        return
    unique_titles: list[str] = []
    for title in detected_titles or (first_item.title,):
        clean = str(title).strip()
        if clean and clean not in unique_titles:
            unique_titles.append(clean)
    if not unique_titles:
        return
    overview = first_item.overview
    method = first_item.method
    weight = first_item.weight
    standards = list(first_item.standards)
    connection.execute(
        """
        UPDATE cases
        SET primary_task_name = ?, task_names_json = ?, summary_overview = ?,
            methods_json = ?, weight_summary = ?, standards_json = ?,
            criteria_json = '[]', title_basis = 'source_detail'
        WHERE case_id = ?
        """,
        (
            unique_titles[0],
            json.dumps(unique_titles, ensure_ascii=False, separators=(",", ":")),
            overview,
            json.dumps([method] if method else [], ensure_ascii=False, separators=(",", ":")),
            weight,
            json.dumps(standards, ensure_ascii=False, separators=(",", ":")),
            case_id,
        ),
    )


def detail_priority(
    *,
    title: str,
    title_basis: str,
    extraction_status: str,
    overview: str,
    method: str,
    weight: str,
    score: str,
    standards: list[object],
    has_rubric: bool,
) -> tuple[str, int, list[str]]:
    category = assessment_category(title, {}, "")
    priority_score = 0
    signals: list[str] = []
    if title_basis in {"heading", "table"} and extraction_status == "bounded":
        priority_score += 18
        signals.append("과제명 원문 경계 확인")
    if standards:
        priority_score += 12
        signals.append("성취기준 연결")
    if has_rubric:
        priority_score += 14
        signals.append("채점기준 원문 확인")
    if method:
        priority_score += 9
        signals.append("평가방법 명시")
    if weight or score:
        priority_score += 8
        signals.append("배점·반영비율 명시")
    if overview:
        priority_score += 7
        signals.append("평가개요 확인")
    compact_title = re.sub(r"\s+", "", title)
    if len(compact_title) <= 3 or compact_title in {
        "발표",
        "탐구",
        "수열",
        "문제",
        "과제",
        "보고서",
        "포트폴리오",
    } or compact_title.endswith("영역"):
        return category, 0, []
    if category and len(compact_title) >= 6:
        priority_score += 8
        signals.append("구체적 수행과제 구조")
    if extraction_status != "bounded" or "원문구간" in compact_title:
        priority_score = max(0, priority_score - 30)
    return category, priority_score, signals


def synchronize_case_summaries(connection: sqlite3.Connection) -> None:
    """Rank every item, then replace every legacy case summary from item one."""

    connection.executescript(
        """
        DROP TABLE IF EXISTS assessment_item_rankings;
        CREATE TABLE assessment_item_rankings (
            item_id TEXT PRIMARY KEY REFERENCES assessment_items(item_id),
            category TEXT NOT NULL,
            priority_score INTEGER NOT NULL,
            priority_signals_json TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE INDEX idx_assessment_item_rankings_category_priority
        ON assessment_item_rankings(category, priority_score DESC, item_id);
        """
    )
    item_rows = connection.execute(
        """
        SELECT item_id, title, title_basis, extraction_status, overview,
               method, weight, score, standards_json, rubric_html_char_count
        FROM assessment_items ORDER BY item_id
        """
    ).fetchall()
    for row in item_rows:
        category, priority_score, signals = detail_priority(
            title=str(row[1]).strip(),
            title_basis=str(row[2]),
            extraction_status=str(row[3]),
            overview=str(row[4]).strip(),
            method=str(row[5]).strip(),
            weight=str(row[6]).strip(),
            score=str(row[7]).strip(),
            standards=json.loads(str(row[8])),
            has_rubric=int(row[9]) > 0,
        )
        connection.execute(
            "INSERT INTO assessment_item_rankings VALUES (?, ?, ?, ?)",
            (
                str(row[0]),
                category,
                priority_score,
                json.dumps(signals, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    rows = connection.execute(
        """
        SELECT status.case_id, status.detected_titles_json,
               item.title, item.overview, item.method, item.weight,
               item.standards_json, item.rubric_html_char_count, item.score,
               ranking.category, ranking.priority_score,
               ranking.priority_signals_json, status.extraction_status,
               case_record.primary_task_name, case_record.task_names_json,
               case_record.title_basis, item.source_html_zlib,
               item.extraction_status
        FROM case_detail_status status
        JOIN cases case_record ON case_record.case_id = status.case_id
        JOIN assessment_items item
          ON item.item_id = (
              SELECT candidate.item_id
              FROM assessment_items candidate
              WHERE candidate.case_id = status.case_id
              ORDER BY CASE WHEN candidate.extraction_status = 'bounded' THEN 0 ELSE 1 END,
                       candidate.item_order
              LIMIT 1
          )
        JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
        ORDER BY status.case_id
        """
    ).fetchall()
    for row in rows:
        detected = json.loads(str(row[1]))
        titles: list[str] = []
        for value in detected if isinstance(detected, list) else []:
            clean = str(value).strip()
            if clean and clean not in titles:
                titles.append(clean)
        if not titles:
            existing_title = str(row[13]).strip()
            existing_basis = str(row[15]).strip()
            source_text = (
                visible_text(zlib.decompress(bytes(row[16])).decode("utf-8"))
                if existing_basis == "table"
                else ""
            )
            if (
                str(row[12]) != "bounded"
                and existing_basis == "table"
                and 2 <= len(existing_title) <= 100
                and existing_title not in {"구체적 과제명 미탐지", "수행평가 원문 구간"}
                and visible_text(existing_title) in source_text
            ):
                titles = [existing_title]
                connection.execute(
                    """
                    UPDATE case_detail_status
                    SET detected_title_count = 1, detected_titles_json = ?
                    WHERE case_id = ?
                    """,
                    (
                        json.dumps(titles, ensure_ascii=False, separators=(",", ":")),
                        str(row[0]),
                    ),
                )
            else:
                titles = [str(row[2]).strip()]
        overview = str(row[3]).strip()
        method = str(row[4]).strip()
        weight = str(row[5]).strip()
        standards = json.loads(str(row[6]))
        has_rubric = int(row[7]) > 0
        score_value = str(row[8]).strip()
        excerpt_parts = [f"수행평가명: {titles[0]}"]
        if overview:
            excerpt_parts.append(f"평가 개요: {overview}")
        if method:
            excerpt_parts.append(f"평가 방법: {method}")
        if weight:
            excerpt_parts.append(f"반영 비율: {weight}")
        if standards:
            excerpt_parts.append("성취기준: " + ", ".join(map(str, standards)))
        excerpt = "\n".join(excerpt_parts)[:902]
        connection.execute(
            """
            UPDATE cases
            SET primary_task_name = ?, task_names_json = ?, summary_overview = ?,
                methods_json = ?, weight_summary = ?, standards_json = ?,
                criteria_json = '[]', title_basis = ?,
                category = ?, priority_score = ?, priority_signals_json = ?,
                review_score = ?, evidence_excerpt = ?, excerpt_char_count = ?,
                rubric_marker_count = ?, achievement_standard_marker_count = ?,
                weight_or_points_marker_count = ?, assessment_method_marker_count = ?
            WHERE case_id = ?
            """,
            (
                titles[0],
                json.dumps(titles, ensure_ascii=False, separators=(",", ":")),
                overview,
                json.dumps(
                    [method] if method else [],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                weight,
                str(row[6]),
                (
                    "source_detail"
                    if str(row[17]) == "bounded"
                    else "source_detail_bundle_review_table_title"
                    if titles[0] != str(row[2]).strip()
                    else "source_detail_bundle_review"
                ),
                str(row[9]),
                int(row[10]),
                str(row[11]),
                int(row[10]),
                excerpt,
                len(excerpt),
                int(has_rubric),
                int(bool(standards)),
                int(bool(weight or score_value)),
                int(bool(method)),
                str(row[0]),
            ),
        )


def build_details(
    connection: sqlite3.Connection,
    catalog_path: Path,
    source_path: Path,
) -> dict[str, object]:
    targets: dict[str, list[dict[str, object]]] = defaultdict(list)
    expected_case_ids: set[str] = set()
    for row in read_jsonl(catalog_path):
        compact = compact_catalog_row(row)
        case_id = str(compact["case_id"])
        if case_id in expected_case_ids:
            raise SystemExit(f"duplicate catalogue case id: {case_id}")
        expected_case_ids.add(case_id)
        targets[str(compact["sha256"])].append(compact)

    database_case_ids = {
        str(row[0]) for row in connection.execute("SELECT case_id FROM cases").fetchall()
    }
    if expected_case_ids != database_case_ids:
        raise SystemExit(
            "catalogue/base database case mismatch: "
            f"catalogue={len(expected_case_ids)} database={len(database_case_ids)} "
            f"missing={len(expected_case_ids - database_case_ids)} "
            f"extra={len(database_case_ids - expected_case_ids)}"
        )

    completed_cases = {
        str(row[0])
        for row in connection.execute("SELECT case_id FROM case_detail_status")
    }
    found_sources = {
        source_sha
        for source_sha, source_targets in targets.items()
        if all(str(target["case_id"]) in completed_cases for target in source_targets)
    }
    status_counts: Counter[str] = Counter(
        {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT extraction_status, COUNT(*) FROM case_detail_status GROUP BY 1"
            )
        }
    )
    format_counts: Counter[str] = Counter(
        {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT source_format, COUNT(*) FROM case_detail_status GROUP BY 1"
            )
        }
    )
    title_basis_counts: Counter[str] = Counter(
        {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT title_basis, COUNT(*) FROM assessment_items GROUP BY 1"
            )
        }
    )
    item_count = int(
        connection.execute("SELECT COUNT(*) FROM assessment_items").fetchone()[0]
    )
    if completed_cases:
        print(
            f"detail_resume cases={len(completed_cases)}/{len(expected_case_ids)} "
            f"sources={len(found_sources)}/{len(targets)}",
            flush=True,
        )
    next_progress = ((len(completed_cases) // 250) + 1) * 250
    for source_number, source_row in read_target_source_jsonl(source_path, set(targets)):
        source_sha = str(source_row.get("sha256") or "")
        if source_sha in found_sources:
            continue
        source_targets = targets.get(source_sha)
        if not source_targets:
            continue
        full_text = str(source_row.get("text") or "")
        full_text_sha = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        for target in source_targets:
            case_id = str(target["case_id"])
            if case_id in completed_cases:
                continue
            section = parse_assessment_section(
                full_text,
                str(target["subject"]),
                tuple(str(value) for value in target["task_name_candidates"]),
            )
            statuses = {item.extraction_status for item in section.items}
            case_status = "bounded" if statuses == {"bounded"} else "bundle_review"
            context_jumps = sum(
                item.source_markdown.count("문맥 전환") for item in section.items
            )
            if context_jumps:
                raise SystemExit(f"context jump leaked into case {case_id}")
            connection.execute(
                "INSERT INTO case_detail_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    str(target["source_format"]),
                    section.boundary_status,
                    case_status,
                    len(section.items),
                    len(section.detected_titles),
                    json.dumps(
                        section.detected_titles,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    len(section.source_markdown),
                    full_text_sha,
                    0,
                ),
            )
            for item in section.items:
                item_id = item_identifier(
                    case_id, item.order, item.source_start, item.title
                )
                connection.execute(
                    """
                    INSERT INTO assessment_items VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        item_id,
                        case_id,
                        item.order,
                        item.title,
                        item.title_raw,
                        item.title_basis,
                        item.extraction_status,
                        item.source_start,
                        item.source_end,
                        item.overview,
                        item.method,
                        item.timing,
                        item.score,
                        item.weight,
                        json.dumps(
                            item.standards,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        compressed_html(item.source_html),
                        compressed_html(item.rubric_html),
                        len(item.source_html),
                        len(item.rubric_html),
                    ),
                )
                title_basis_counts[item.title_basis] += 1
                item_count += 1
            update_case_summary(
                connection,
                case_id,
                section.detected_titles,
                section.items[0],
            )
            completed_cases.add(case_id)
            status_counts[case_status] += 1
            format_counts[str(target["source_format"])] += 1
        found_sources.add(source_sha)
        if len(completed_cases) >= next_progress:
            connection.commit()
            print(
                f"detail_progress cases={len(completed_cases)}/{len(expected_case_ids)} "
                f"source_rows={source_number}",
                flush=True,
            )
            next_progress = ((len(completed_cases) // 250) + 1) * 250
        if len(found_sources) == len(targets):
            break

    missing_sources = set(targets) - found_sources
    missing_cases = expected_case_ids - completed_cases
    if missing_sources or missing_cases:
        raise SystemExit(
            f"full-text coverage failed: missing_sources={len(missing_sources)} "
            f"missing_cases={len(missing_cases)}"
        )
    return {
        "cases": len(completed_cases),
        "items": item_count,
        "case_status": dict(sorted(status_counts.items())),
        "source_formats": dict(sorted(format_counts.items())),
        "title_basis": dict(sorted(title_basis_counts.items())),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_school_subject_catalog_v2.jsonl",
    )
    parser.add_argument(
        "--source-jsonl",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_all_subject_evidence_v2_source.jsonl",
    )
    parser.add_argument(
        "--base-db",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_detail_manifest.json",
    )
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Continue an intact checkpoint database created by a previous run.",
    )
    args = parser.parse_args()
    missing = [
        str(path)
        for path in (args.catalog, args.source_jsonl, args.base_db)
        if not path.is_file()
    ]
    if missing:
        raise SystemExit(f"missing inputs: {missing}")
    if (args.output.exists() or args.manifest_output.exists()) and not args.replace:
        raise SystemExit("output exists; use --replace for an atomic rebuild")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.resume_from:
        temp_path = args.resume_from.resolve()
        if not temp_path.is_file():
            raise SystemExit(f"resume checkpoint not found: {temp_path}")
    else:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent
        )
        os.close(descriptor)
        temp_path = Path(temp_name)
    started = dt.datetime.now(dt.UTC)
    if not args.resume_from:
        shutil.copy2(args.base_db, temp_path)
    try:
        with closing(sqlite3.connect(temp_path)) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA foreign_keys = ON")
            if not args.resume_from:
                connection.executescript(
                    "DROP TABLE IF EXISTS assessment_items;"
                    "DROP TABLE IF EXISTS case_detail_status;"
                )
                connection.executescript(SCHEMA_SQL)
            else:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                if integrity != "ok":
                    raise SystemExit(f"resume checkpoint integrity failed: {integrity}")
            counts = build_details(connection, args.catalog, args.source_jsonl)
            synchronize_case_summaries(connection)
            connection.execute("PRAGMA user_version = 2")
            connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                (
                    "detail_schema_version",
                    json.dumps(2, separators=(",", ":")),
                ),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                (
                    "detail_unit_of_analysis",
                    json.dumps(
                        "one source-bounded performance assessment item",
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"SQLite integrity check failed: {integrity}")
            connection.execute("VACUUM")
        os.replace(temp_path, args.output)
    except BaseException:
        print(f"detail_checkpoint={temp_path}", file=sys.stderr, flush=True)
        raise

    completed = dt.datetime.now(dt.UTC)
    manifest = {
        "schema_version": 2,
        "generated_at": completed.isoformat(timespec="seconds"),
        "elapsed_seconds": round((completed - started).total_seconds(), 3),
        "inputs": {
            "catalog": str(args.catalog.resolve()),
            "source_jsonl": str(args.source_jsonl.resolve()),
            "base_db": str(args.base_db.resolve()),
        },
        "output": {
            "path": str(args.output.resolve()),
            "bytes": args.output.stat().st_size,
            "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        },
        "counts": counts,
        "quality_gates": {
            # build_details already raises when any catalogue case is missing;
            # do not freeze this gate to the original 8,800-row release.
            "all_catalog_cases_have_detail": counts["cases"] > 0,
            "context_jump_markers": 0,
            "source_html_encoding": "zlib-utf8-v1",
            "titles_are_source_bounded": True,
        },
    }
    manifest_temp = args.manifest_output.with_suffix(
        args.manifest_output.suffix + ".partial"
    )
    manifest_temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(manifest_temp, args.manifest_output)
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
