"""Conservatively repair the generated detail layer without touching originals."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_detail_db import value_is_traceable, visible_text
from scripts.build_math_assessment_detail_db import synchronize_case_summaries
from scripts.math_assessment_detail_parser import (
    PERFORMANCE_MARKER_RE,
    balance_table_tags,
    explicit_segment_title,
    heading_title_is_structural,
    segment_subject_alignment,
)

SYNTHETIC_BUNDLE_TITLE = "수행평가 원문 구간"
TRACEABLE_FIELDS = ("overview", "method", "timing", "score", "weight")


def repair(
    connection: sqlite3.Connection,
    base_titles: dict[str, tuple[str, str]] | None = None,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    rows = connection.execute(
        """
        SELECT item.item_id, item.title, item.title_raw, item.title_basis,
               item.extraction_status, item.overview, item.method, item.timing,
               item.score, item.weight, item.standards_json,
               item.source_html_zlib, item.rubric_html_zlib,
               status.boundary_status, cases.subject, item.case_id
        FROM assessment_items item
        JOIN case_detail_status status ON status.case_id = item.case_id
        JOIN cases ON cases.case_id = item.case_id
        ORDER BY item.item_id
        """
    ).fetchall()
    for row in rows:
        original_source_html = zlib.decompress(row[11]).decode("utf-8")
        original_rubric_html = zlib.decompress(row[12]).decode("utf-8")
        source_html = balance_table_tags(original_source_html)
        rubric_html = balance_table_tags(original_rubric_html)
        source_text = visible_text(source_html)
        title = str(row[1])
        title_raw = str(row[2])
        title_basis = str(row[3])
        extraction_status = str(row[4])
        field_values = {name: str(row[5 + index]) for index, name in enumerate(TRACEABLE_FIELDS)}
        standards = json.loads(str(row[10]))

        alignment = segment_subject_alignment(source_html, str(row[14]))
        short_boundary_unknown = (
            str(row[13]).startswith("subject_mention_only:")
            and alignment == "unknown"
        )
        if alignment == "other" or short_boundary_unknown:
            title = SYNTHETIC_BUNDLE_TITLE
            title_raw = SYNTHETIC_BUNDLE_TITLE
            title_basis = "unbounded_bundle"
            extraction_status = (
                "source_mismatch_review" if alignment == "other" else "bundle_review"
            )
            field_values = {name: "" for name in TRACEABLE_FIELDS}
            standards = []
            counts[f"subject_alignment_{alignment}_items_demoted"] += 1

        # Prefer a source-authored table label over a surrounding numbered
        # document heading.  For example, ``수행평가 세부 계획`` is structure;
        # ``평가 영역명 | 변화율 모델링 탐구`` is the actual assessment name.
        table_title = (
            explicit_segment_title(source_html)
            if extraction_status == "bounded"
            else ""
        )
        if table_title and table_title != title:
            title = table_title
            title_raw = table_title
            title_basis = "table"
            extraction_status = "bounded"
            counts["titles_replaced_from_explicit_table_label"] += 1
        elif extraction_status == "bounded" and (
            heading_title_is_structural(title)
            or not PERFORMANCE_MARKER_RE.search(source_text)
        ):
            title = SYNTHETIC_BUNDLE_TITLE
            title_raw = SYNTHETIC_BUNDLE_TITLE
            title_basis = "unbounded_bundle"
            extraction_status = "bundle_review"
            field_values = {name: "" for name in TRACEABLE_FIELDS}
            standards = []
            if heading_title_is_structural(title):
                counts["structural_headings_demoted_to_review_bundle"] += 1
            else:
                counts["unit_or_standard_headings_demoted_to_review_bundle"] += 1

        title_is_synthetic = (
            title_basis == "unbounded_bundle" and title_raw == SYNTHETIC_BUNDLE_TITLE
        )
        if not title_is_synthetic and not value_is_traceable(title_raw, source_text):
            if value_is_traceable(title, source_text):
                title_raw = title
                counts["title_raw_replaced_with_traceable_title"] += 1
            else:
                title = SYNTHETIC_BUNDLE_TITLE
                title_raw = SYNTHETIC_BUNDLE_TITLE
                title_basis = "unbounded_bundle"
                extraction_status = "bundle_review"
                field_values = {name: "" for name in TRACEABLE_FIELDS}
                standards = []
                counts["items_demoted_to_review_bundle"] += 1

        for name, value in list(field_values.items()):
            if value and not value_is_traceable(value, source_text):
                field_values[name] = ""
                counts[f"cleared_untraceable_{name}"] += 1
        if any(not value_is_traceable(str(value), source_text) for value in standards):
            standards = []
            counts["cleared_untraceable_standards"] += 1

        if source_html.count("</table>") != original_source_html.count("</table>"):
            counts["balanced_source_html"] += 1
        if rubric_html.count("</table>") != original_rubric_html.count("</table>"):
            counts["balanced_rubric_html"] += 1

        connection.execute(
            """
            UPDATE assessment_items
            SET title = ?, title_raw = ?, title_basis = ?, extraction_status = ?,
                overview = ?, method = ?, timing = ?, score = ?, weight = ?,
                standards_json = ?, source_html_zlib = ?, rubric_html_zlib = ?,
                source_html_char_count = ?, rubric_html_char_count = ?
            WHERE item_id = ?
            """,
            (
                title,
                title_raw,
                title_basis,
                extraction_status,
                field_values["overview"],
                field_values["method"],
                field_values["timing"],
                field_values["score"],
                field_values["weight"],
                json.dumps(standards, ensure_ascii=False, separators=(",", ":")),
                (
                    row[11]
                    if source_html == original_source_html
                    else zlib.compress(source_html.encode("utf-8"), level=9)
                ),
                (
                    row[12]
                    if rubric_html == original_rubric_html
                    else zlib.compress(rubric_html.encode("utf-8"), level=9)
                ),
                len(source_html),
                len(rubric_html),
                str(row[0]),
            ),
        )

    for (case_id,) in connection.execute("SELECT case_id FROM case_detail_status"):
        items = connection.execute(
            """
            SELECT title, title_basis, extraction_status
            FROM assessment_items WHERE case_id = ? ORDER BY item_order
            """,
            (case_id,),
        ).fetchall()
        case_status = (
            "bounded"
            if items and all(str(item[2]) == "bounded" for item in items)
            else "bundle_review"
        )
        detected = (
            [str(item[0]) for item in items]
            if case_status == "bounded"
            else [str(items[0][0])]
            if len(items) == 1 and str(items[0][1]) == "table_bundle"
            else []
        )
        if not detected and base_titles:
            base_title, base_basis = base_titles.get(str(case_id), ("", ""))
            first_source = connection.execute(
                """
                SELECT source_html_zlib FROM assessment_items
                WHERE case_id = ? ORDER BY item_order LIMIT 1
                """,
                (case_id,),
            ).fetchone()
            source_text = (
                visible_text(zlib.decompress(first_source[0]).decode("utf-8"))
                if first_source
                else ""
            )
            if (
                base_basis == "table"
                and 2 <= len(base_title) <= 100
                and base_title not in {"구체적 과제명 미탐지", SYNTHETIC_BUNDLE_TITLE}
                and visible_text(base_title) in source_text
            ):
                detected = [base_title]
                connection.execute(
                    """
                    UPDATE cases
                    SET primary_task_name = ?, task_names_json = ?, title_basis = 'table'
                    WHERE case_id = ?
                    """,
                    (
                        base_title,
                        json.dumps(detected, ensure_ascii=False, separators=(",", ":")),
                        str(case_id),
                    ),
                )
                counts["bundle_cases_recovered_from_source_confirmed_table_title"] += 1
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
        "--manifest",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_detail_manifest.json",
    )
    parser.add_argument(
        "--base-db",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    args = parser.parse_args()
    with sqlite3.connect(args.base_db) as base_connection:
        base_titles = {
            str(case_id): (str(title).strip(), str(basis).strip())
            for case_id, title, basis in base_connection.execute(
                "SELECT case_id, primary_task_name, title_basis FROM cases"
            )
        }
    descriptor, temp_name = tempfile.mkstemp(
        prefix=args.database.stem + "_repair_", suffix=".partial", dir=args.database.parent
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    shutil.copy2(args.database, temporary)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA foreign_keys = ON")
            counts = repair(connection, base_titles)
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("repaired database failed integrity_check")
            connection.execute("VACUUM")
        try:
            os.replace(temporary, args.database)
        except PermissionError:
            # Windows search/indexing services can briefly hold the destination
            # path open even after every SQLite connection in this process is
            # closed. SQLite's backup API updates the database transactionally
            # without relying on a filesystem rename.
            with sqlite3.connect(temporary) as source, sqlite3.connect(
                args.database
            ) as destination:
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                # The completed checkpoint is harmless and can be removed by a
                # later cleanup pass once the Windows indexer releases it.
                print(f"repair_completed_checkpoint_retained={temporary}")
    except BaseException:
        print(f"repair_checkpoint={temporary}")
        raise

    if args.manifest.exists():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    else:
        # Recovery and audit databases are intentionally built outside the
        # production publish directory.  Those isolated runs may not have a
        # pre-existing detail manifest, so create the same minimal envelope
        # instead of failing after the database repair has already succeeded.
        manifest = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "output": {"path": str(args.database.resolve())},
        }
    manifest["repair"] = counts
    with sqlite3.connect(args.database) as connection:
        manifest["counts"] = {
            "cases": int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]),
            "items": int(
                connection.execute("SELECT COUNT(*) FROM assessment_items").fetchone()[0]
            ),
            "item_status": {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT extraction_status, COUNT(*) FROM assessment_items GROUP BY 1"
                )
            },
            "source_mismatch_cases": int(
                connection.execute(
                    "SELECT COUNT(DISTINCT case_id) FROM assessment_items "
                    "WHERE extraction_status = 'source_mismatch_review'"
                ).fetchone()[0]
            ),
            "case_status": {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT extraction_status, COUNT(*) FROM case_detail_status GROUP BY 1"
                )
            },
            "source_formats": {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT source_format, COUNT(*) FROM case_detail_status GROUP BY 1"
                )
            },
            "title_basis": {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT title_basis, COUNT(*) FROM assessment_items GROUP BY 1"
                )
            },
        }
    output = manifest.setdefault("output", {})
    output["path"] = str(args.database.resolve())
    output["bytes"] = args.database.stat().st_size
    output["sha256"] = hashlib.sha256(args.database.read_bytes()).hexdigest()
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_temp = args.manifest.with_suffix(args.manifest.suffix + ".partial")
    manifest_temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(manifest_temp, args.manifest)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
