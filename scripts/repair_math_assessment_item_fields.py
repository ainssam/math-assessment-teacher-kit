"""Re-extract public item facts into a new database without touching sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_detail_db import value_is_traceable, visible_text
from scripts.build_math_assessment_detail_db import synchronize_case_summaries
from scripts.math_assessment_detail_parser import _exact_fields


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("overview", "method", "timing", "score", "weight")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".tmp" / "math_assessment_catalog_detail_precision.sqlite",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "derived" / "math_assessment_item_field_repair_report.json",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    source_hash_before = sha256(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    shutil.copy2(args.source, temporary)

    connection = sqlite3.connect(temporary)
    connection.row_factory = sqlite3.Row
    counts: Counter[str] = Counter()
    samples: list[dict[str, object]] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT item_id, case_id, title, overview, method, timing, score,
                   weight, source_html_zlib
            FROM assessment_items
            WHERE extraction_status = 'bounded'
              AND title_basis IN ('table', 'heading')
            ORDER BY case_id, item_order
            """
        ).fetchall()
        for index, row in enumerate(rows, 1):
            source_html = zlib.decompress(bytes(row["source_html_zlib"])).decode("utf-8")
            source_text = visible_text(source_html)
            exact = _exact_fields(source_html)
            replacements: dict[str, str] = {}
            changed: dict[str, dict[str, str]] = {}
            for field in FIELDS:
                old = str(row[field] or "").strip()
                new = str(exact.get(field) or "").strip()
                if new and not value_is_traceable(new, source_text):
                    raise RuntimeError(
                        f"untraceable {field} candidate for {row['item_id']}: {new}"
                    )
                replacements[field] = new
                if old != new:
                    counts[f"changed_{field}"] += 1
                    if old and not new:
                        counts[f"cleared_{field}"] += 1
                    elif new and not old:
                        counts[f"recovered_{field}"] += 1
                    else:
                        counts[f"replaced_{field}"] += 1
                    changed[field] = {"old": old[:240], "new": new[:240]}
            if changed:
                counts["changed_items"] += 1
                if len(samples) < 100:
                    samples.append(
                        {
                            "item_id": str(row["item_id"]),
                            "case_id": str(row["case_id"]),
                            "title": str(row["title"]),
                            "changes": changed,
                        }
                    )
                connection.execute(
                    """
                    UPDATE assessment_items
                    SET overview = ?, method = ?, timing = ?, score = ?, weight = ?
                    WHERE item_id = ?
                    """,
                    (
                        replacements["overview"],
                        replacements["method"],
                        replacements["timing"],
                        replacements["score"],
                        replacements["weight"],
                        str(row["item_id"]),
                    ),
                )
            counts["public_items_reviewed"] += 1
            if index % 2000 == 0:
                print(f"field repair {index}/{len(rows)}", flush=True)

        synchronize_case_summaries(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"candidate database integrity failed: {integrity}")
        connection.commit()
        connection.execute("VACUUM")
    except BaseException:
        connection.rollback()
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    args.output.unlink(missing_ok=True)
    temporary.replace(args.output)

    source_hash_after = sha256(args.source)
    if source_hash_before != source_hash_after:
        raise RuntimeError("source database changed during isolated field repair")
    report = {
        "schema_version": 1,
        "source_database": str(args.source.resolve()),
        "source_database_sha256": source_hash_after,
        "candidate_database": str(args.output.resolve()),
        "candidate_database_sha256": sha256(args.output),
        "counts": dict(sorted(counts.items())),
        "samples": samples,
        "source_database_unchanged": True,
        "promotion_applied": False,
        "policy": (
            "Only field values selected by an explicit source label and a field-specific "
            "shape are retained. Empty is preferred to an inferred or neighbouring value."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
