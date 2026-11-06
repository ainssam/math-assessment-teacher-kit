"""Promote only source-verified title candidates from the recovery audit.

This deliberately does not split a bundle into guessed item boundaries.  For a
source bundle with several explicit assessment-name cells, the detail page
continues to show one original bundle and lists every recovered source title.
The catalogue summary can therefore stop calling that school plan
``수행평가명 미확정`` without pretending each rubric was individually split.
"""

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
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_detail_db import value_is_traceable, visible_text
from scripts.build_math_assessment_detail_db import synchronize_case_summaries

SYNTHETIC_BUNDLE_TITLE = "수행평가 원문 구간"
REQUIRED_HIGH_FIELDS = {
    "confidence": "high",
    "detection": "table_row",
    "subject_alignment": "expected",
    "explicit_name_label": True,
    "title_looks_complete": True,
}


def read_audit(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise SystemExit(f"title recovery audit is malformed: {path}")
    return value


def candidates_by_case(audit: dict[str, object]) -> tuple[dict[str, list[str]], Counter[str]]:
    selected: dict[str, list[str]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    for record in audit["candidates"]:
        if not isinstance(record, dict):
            skipped["invalid_record"] += 1
            continue
        if any(record.get(field) != expected for field, expected in REQUIRED_HIGH_FIELDS.items()):
            skipped["not_source_verified_high"] += 1
            continue
        if bool(record.get("other_subject_signal")):
            skipped["other_subject_signal"] += 1
            continue
        case_id = str(record.get("case_id") or "")
        title = str(record.get("candidate") or "").strip()
        if not case_id or not title or title == SYNTHETIC_BUNDLE_TITLE:
            skipped["missing_case_or_title"] += 1
            continue
        if title not in selected[case_id]:
            selected[case_id].append(title)
    return dict(selected), skipped


def source_text_for_case(connection: sqlite3.Connection, case_id: str) -> str:
    rows = connection.execute(
        "SELECT source_html_zlib FROM assessment_items WHERE case_id = ? ORDER BY item_order",
        (case_id,),
    ).fetchall()
    return "\n".join(
        visible_text(zlib.decompress(bytes(row[0])).decode("utf-8")) for row in rows
    )


def promote(connection: sqlite3.Connection, requested: dict[str, list[str]]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    promoted: dict[str, list[str]] = {}
    for case_id, titles in sorted(requested.items()):
        case = connection.execute(
            """
            SELECT c.title_basis, status.extraction_status
            FROM cases c
            JOIN case_detail_status status USING (case_id)
            WHERE c.case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if case is None:
            counts["missing_case"] += 1
            continue
        if str(case[0]) != "source_detail_bundle_review" or str(case[1]) != "bundle_review":
            counts["not_unresolved_bundle"] += 1
            continue
        source_text = source_text_for_case(connection, case_id)
        traceable = [title for title in titles if value_is_traceable(title, source_text)]
        if not traceable:
            counts["untraceable_title_rejected"] += 1
            continue
        connection.execute(
            """
            UPDATE case_detail_status
            SET detected_title_count = ?, detected_titles_json = ?
            WHERE case_id = ?
            """,
            (
                len(traceable),
                json.dumps(traceable, ensure_ascii=False, separators=(",", ":")),
                case_id,
            ),
        )
        promoted[case_id] = traceable
        counts["promoted_cases"] += 1
        counts["promoted_titles"] += len(traceable)
        counts[f"titles_per_case_{len(traceable)}"] += 1

    synchronize_case_summaries(connection)
    return {
        "counts": dict(sorted(counts.items())),
        "promoted": promoted,
    }


def output_manifest(
    *,
    database: Path,
    audit: Path,
    requested: dict[str, list[str]],
    skipped: Counter[str],
    result: dict[str, object],
    started: dt.datetime,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round((dt.datetime.now(dt.UTC) - started).total_seconds(), 3),
        "database": {
            "path": str(database.resolve()),
            "bytes": database.stat().st_size,
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        },
        "audit": str(audit.resolve()),
        "requested": {
            "cases": len(requested),
            "titles": sum(len(titles) for titles in requested.values()),
            "skipped_candidates": dict(sorted(skipped.items())),
        },
        "result": result,
        "policy": (
            "Only direct source-table name labels with an expected subject-standard "
            "alignment are promoted. Multi-title source bundles remain unsplit."
        ),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_unresolved_title_recovery_audit.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_title_recovery_manifest.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate title candidates but do not change the SQLite catalogue",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    audit_path = args.audit.resolve()
    if not database.is_file():
        raise SystemExit(f"detail database not found: {database}")
    audit = read_audit(audit_path)
    requested, skipped = candidates_by_case(audit)
    started = dt.datetime.now(dt.UTC)

    if args.dry_run:
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            traceable_cases = 0
            traceable_titles = 0
            for case_id, titles in requested.items():
                source_text = source_text_for_case(connection, case_id)
                traceable = [title for title in titles if value_is_traceable(title, source_text)]
                traceable_cases += int(bool(traceable))
                traceable_titles += len(traceable)
        report = {
            "dry_run": True,
            "requested_cases": len(requested),
            "requested_titles": sum(len(titles) for titles in requested.values()),
            "traceable_cases": traceable_cases,
            "traceable_titles": traceable_titles,
            "skipped_candidates": dict(sorted(skipped.items())),
        }
        print(json.dumps(report, ensure_ascii=False))
        return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{database.stem}_title_recovery_",
        suffix=".partial",
        dir=database.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    shutil.copy2(database, temporary)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = NORMAL")
            result = promote(connection, requested)
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"title recovery database failed integrity_check: {integrity}")
        try:
            os.replace(temporary, database)
        except PermissionError:
            # A local API preview can briefly hold a read handle on Windows.
            # SQLite backup preserves the same transactional replacement without
            # removing the original path underneath that process.
            with sqlite3.connect(temporary) as source, sqlite3.connect(database) as destination:
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                # The completed temporary copy is safe to leave for Windows
                # indexing to release; do not mark a successful promotion as
                # failed merely because cleanup is delayed.
                print(f"title_recovery_checkpoint_retained={temporary}", flush=True)
    except BaseException:
        print(f"title_recovery_checkpoint={temporary}", flush=True)
        raise

    manifest = output_manifest(
        database=database,
        audit=audit_path,
        requested=requested,
        skipped=skipped,
        result=result,
        started=started,
    )
    temporary_manifest = args.manifest.with_suffix(args.manifest.suffix + ".partial")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, args.manifest)
    print(json.dumps(manifest["result"], ensure_ascii=False))


if __name__ == "__main__":
    main()
