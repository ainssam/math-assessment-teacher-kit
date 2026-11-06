"""Quarantine structurally flagged assessment items in an isolated database.

The source and rubric HTML blobs are preserved byte-for-byte.  Only derived
public fields are cleared and the item is moved to ``bundle_review``.  This is
used for conservative recovery releases: a structural signal is never treated
as proof that inferred table cells are safe to publish.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from build_math_assessment_detail_db import synchronize_case_summaries


SYNTHETIC_TITLE = "수행평가 원문 구간"


def read_flagged_item_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("item_id") or "").strip()
            for row in csv.DictReader(handle)
            if str(row.get("item_id") or "").strip()
        }


def quarantine(connection: sqlite3.Connection, item_ids: set[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    counts["flagged_item_ids"] = len(item_ids)
    if not item_ids:
        return dict(counts)

    placeholders = ",".join("?" for _ in item_ids)
    existing = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            f"SELECT item_id, extraction_status FROM assessment_items "
            f"WHERE item_id IN ({placeholders})",
            sorted(item_ids),
        )
    }
    counts["flagged_items_found"] = len(existing)
    counts["flagged_items_missing"] = len(item_ids - set(existing))
    bounded_ids = sorted(
        item_id for item_id, status in existing.items() if status == "bounded"
    )
    if bounded_ids:
        bounded_placeholders = ",".join("?" for _ in bounded_ids)
        connection.execute(
            f"""
            UPDATE assessment_items
            SET title = ?, title_raw = ?, title_basis = 'unbounded_bundle',
                extraction_status = 'bundle_review', overview = '', method = '',
                timing = '', score = '', weight = '', standards_json = '[]'
            WHERE item_id IN ({bounded_placeholders})
            """,
            [SYNTHETIC_TITLE, SYNTHETIC_TITLE, *bounded_ids],
        )
    counts["bounded_items_quarantined"] = len(bounded_ids)
    counts["already_nonpublic_flagged_items"] = len(existing) - len(bounded_ids)

    for (case_id,) in connection.execute(
        "SELECT case_id FROM case_detail_status ORDER BY case_id"
    ):
        rows = connection.execute(
            """
            SELECT title, extraction_status FROM assessment_items
            WHERE case_id = ? ORDER BY item_order
            """,
            (case_id,),
        ).fetchall()
        titles = list(
            dict.fromkeys(
                str(title)
                for title, status in rows
                if str(status) == "bounded" and str(title).strip()
            )
        )
        status = "bounded" if titles else "bundle_review"
        connection.execute(
            """
            UPDATE case_detail_status
            SET extraction_status = ?, detected_title_count = ?,
                detected_titles_json = ?
            WHERE case_id = ?
            """,
            (
                status,
                len(titles),
                json.dumps(titles, ensure_ascii=False, separators=(",", ":")),
                str(case_id),
            ),
        )

    synchronize_case_summaries(connection)
    counts["remaining_public_items"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'"
        ).fetchone()[0]
    )
    counts["remaining_public_cases"] = int(
        connection.execute(
            "SELECT COUNT(DISTINCT case_id) FROM assessment_items "
            "WHERE extraction_status = 'bounded'"
        ).fetchone()[0]
    )
    return dict(sorted(counts.items()))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audit-queue", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root
        / "data"
        / "derived"
        / "math_assessment_structural_quarantine_manifest.json",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    item_ids = read_flagged_item_ids(args.audit_queue)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=database.stem + "_structural_quarantine_",
        suffix=".partial",
        dir=database.parent,
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    shutil.copy2(database, temporary)
    started = dt.datetime.now(dt.UTC)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            counts = quarantine(connection, item_ids)
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise SystemExit(f"quarantined database failed integrity_check: {integrity}")
        try:
            os.replace(temporary, database)
        except PermissionError:
            with sqlite3.connect(temporary) as source, sqlite3.connect(
                database
            ) as destination:
                source.backup(destination)
                destination.commit()
            try:
                temporary.unlink()
            except PermissionError:
                print(f"structural_quarantine_checkpoint_retained={temporary}", flush=True)
    except BaseException:
        print(f"structural_quarantine_checkpoint={temporary}", flush=True)
        raise

    manifest = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round(
            (dt.datetime.now(dt.UTC) - started).total_seconds(), 3
        ),
        "database": {
            "path": str(database),
            "bytes": database.stat().st_size,
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        },
        "audit_queue": str(args.audit_queue.resolve()),
        "counts": counts,
        "policy": (
            "All structurally flagged public items are hidden in the isolated "
            "recovery release; compressed source and rubric HTML are preserved."
        ),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
