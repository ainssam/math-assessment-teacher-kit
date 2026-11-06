"""Quarantine titles that fail the conservative source-title audit.

The original compressed source remains untouched.  Only derived public fields
are cleared, and the item becomes a non-public review bundle.  The database is
updated through a checked temporary copy so a failed run cannot damage the
published catalogue.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from audit_math_assessment_titles_full import audit_flags, confidence
from build_math_assessment_detail_db import synchronize_case_summaries

SYNTHETIC_TITLE = "수행평가 원문 구간"
MAX_PUBLIC_ITEMS_PER_CASE = 12


def rejected(title: str, basis: str) -> bool:
    return confidence(audit_flags(str(title).strip(), str(basis)), str(basis)) == "reject"


def quarantine(connection: sqlite3.Connection) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in connection.execute(
        "SELECT item_id, title, title_basis, extraction_status FROM assessment_items"
    ).fetchall():
        item_id, title, basis, extraction_status = map(str, row)
        if not rejected(title, basis):
            continue
        next_status = (
            "source_mismatch_review"
            if extraction_status == "source_mismatch_review"
            else "bundle_review"
        )
        connection.execute(
            """
            UPDATE assessment_items
            SET title = ?, title_raw = ?, title_basis = 'unbounded_bundle',
                extraction_status = ?, overview = '', method = '', timing = '',
                score = '', weight = '', standards_json = '[]'
            WHERE item_id = ?
            """,
            (SYNTHETIC_TITLE, SYNTHETIC_TITLE, next_status, item_id),
        )
        counts["items_quarantined"] += 1

    implausible_cases = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT case_id
            FROM assessment_items
            WHERE extraction_status = 'bounded'
              AND title_basis IN ('table', 'heading')
            GROUP BY case_id
            HAVING COUNT(*) > ?
            """,
            (MAX_PUBLIC_ITEMS_PER_CASE,),
        )
    ]
    for case_id in implausible_cases:
        cursor = connection.execute(
            """
            UPDATE assessment_items
            SET title = ?, title_raw = ?, title_basis = 'unbounded_bundle',
                extraction_status = 'bundle_review', overview = '', method = '',
                timing = '', score = '', weight = '', standards_json = '[]'
            WHERE case_id = ? AND extraction_status = 'bounded'
            """,
            (SYNTHETIC_TITLE, SYNTHETIC_TITLE, case_id),
        )
        counts["implausible_item_count_cases_quarantined"] += 1
        counts["implausible_item_count_items_quarantined"] += cursor.rowcount

    for row in connection.execute(
        "SELECT case_id, detected_titles_json FROM case_detail_status"
    ).fetchall():
        case_id, raw_titles = str(row[0]), str(row[1])
        try:
            titles = json.loads(raw_titles)
        except json.JSONDecodeError:
            titles = []
        titles = titles if isinstance(titles, list) else []
        kept: list[str] = []
        for raw_title in titles:
            title = str(raw_title).strip()
            if not title or rejected(title, "source_detail_bundle_review_table_title"):
                counts["detected_titles_quarantined"] += int(bool(title))
                continue
            if title not in kept:
                kept.append(title)
        items = connection.execute(
            "SELECT extraction_status FROM assessment_items WHERE case_id = ? ORDER BY item_order",
            (case_id,),
        ).fetchall()
        case_status = (
            "bounded"
            if items and all(str(item[0]) == "bounded" for item in items)
            else "bundle_review"
        )
        connection.execute(
            """
            UPDATE case_detail_status
            SET extraction_status = ?, detected_title_count = ?, detected_titles_json = ?
            WHERE case_id = ?
            """,
            (
                case_status,
                len(kept),
                json.dumps(kept, ensure_ascii=False, separators=(",", ":")),
                case_id,
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
        default=root / "data" / "derived" / "math_assessment_title_quarantine_manifest.json",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    descriptor, name = tempfile.mkstemp(
        prefix=database.stem + "_title_quarantine_", suffix=".partial", dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    shutil.copy2(database, temporary)
    started = dt.datetime.now(dt.UTC)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            counts = quarantine(connection)
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("quarantined database failed integrity_check")
        try:
            os.replace(temporary, database)
        except PermissionError:
            with sqlite3.connect(temporary) as source, sqlite3.connect(database) as destination:
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                print(f"title_quarantine_checkpoint_retained={temporary}", flush=True)
    except BaseException:
        print(f"title_quarantine_checkpoint={temporary}", flush=True)
        raise

    manifest = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round((dt.datetime.now(dt.UTC) - started).total_seconds(), 3),
        "database": {
            "path": str(database),
            "bytes": database.stat().st_size,
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        },
        "counts": counts,
        "policy": (
            "Rejected derived titles and cases with more than 12 public items are hidden; "
            "original compressed source is preserved."
        ),
    }
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
