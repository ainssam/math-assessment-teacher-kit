"""Apply accepted explicit-item proposals to a separate candidate database."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sqlite3
import sys
import zlib
from collections import Counter
from pathlib import Path

from audit_math_assessment_table_structure import restore_escaped_table_rows

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        / "math_assessment_explicit_item_recovery_proposals.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / ".tmp"
        / "math_assessment_catalog_detail_explicit_recovery.sqlite",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_explicit_item_recovery_apply_report.json",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_accepted(path: Path) -> list[dict[str, object]]:
    accepted: list[dict[str, object]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"proposal row must be object: {path}:{line_number}")
            if row.get("decision") != "accepted":
                continue
            item_id = str(row.get("item_id") or "")
            if not item_id or item_id in seen:
                raise ValueError(f"duplicate or empty accepted item: {path}:{line_number}")
            seen.add(item_id)
            accepted.append(row)
    return accepted


def synchronize_summaries(connection: sqlite3.Connection) -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    module = importlib.import_module("scripts.build_math_assessment_detail_db")
    module.synchronize_case_summaries(connection)


def main() -> None:
    args = parse_args()
    source = args.database.resolve()
    accepted = load_accepted(args.proposals)
    if not accepted:
        raise SystemExit("no accepted explicit-item recovery proposals")

    source_hash_before = file_sha256(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f"{args.output.name}.partial")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)

    connection = sqlite3.connect(temporary)
    connection.row_factory = sqlite3.Row
    counts: Counter[str] = Counter()
    affected_cases: set[str] = set()
    before_bounded = int(
        connection.execute(
            "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'"
        ).fetchone()[0]
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        for proposal in accepted:
            item_id = str(proposal["item_id"])
            row = connection.execute(
                """
                SELECT item_id, case_id, title, title_basis, extraction_status,
                       source_html_zlib
                FROM assessment_items WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"accepted item is missing: {item_id}")
            if str(row["case_id"]) != str(proposal["case_id"]):
                raise RuntimeError(f"accepted case changed: {item_id}")
            if str(row["title"]) != str(proposal["title"]):
                raise RuntimeError(f"accepted title changed: {item_id}")
            if str(row["title_basis"]) != "table":
                raise RuntimeError(f"accepted title basis changed: {item_id}")
            if str(row["extraction_status"]) != "bundle_review":
                raise RuntimeError(f"accepted status changed: {item_id}")
            source_html = restore_escaped_table_rows(
                zlib.decompress(bytes(row["source_html_zlib"])).decode(
                    "utf-8", errors="replace"
                )
            )
            actual_hash = hashlib.sha256(source_html.encode("utf-8")).hexdigest()
            if actual_hash != str(proposal["source_html_sha256"]):
                raise RuntimeError(f"accepted source HTML changed: {item_id}")
            connection.execute(
                "UPDATE assessment_items SET extraction_status = 'bounded' WHERE item_id = ?",
                (item_id,),
            )
            affected_cases.add(str(row["case_id"]))
            counts["items_promoted"] += 1

        for case_id in affected_cases:
            titles = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT title FROM assessment_items
                    WHERE case_id = ? AND extraction_status = 'bounded'
                      AND title_basis IN ('table', 'heading')
                    ORDER BY item_order
                    """,
                    (case_id,),
                )
            ]
            connection.execute(
                """
                UPDATE case_detail_status
                SET extraction_status = 'bounded',
                    assessment_item_count = (
                        SELECT COUNT(*) FROM assessment_items WHERE case_id = ?
                    ),
                    detected_title_count = ?, detected_titles_json = ?
                WHERE case_id = ?
                """,
                (
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
        after_bounded = int(
            connection.execute(
                "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'"
            ).fetchone()[0]
        )
        if after_bounded - before_bounded != len(accepted):
            raise RuntimeError(
                "bounded delta mismatch: "
                f"before={before_bounded} after={after_bounded} accepted={len(accepted)}"
            )
        counts["affected_cases"] = len(affected_cases)
        counts["bounded_before"] = before_bounded
        counts["bounded_after"] = after_bounded
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()

    if file_sha256(source) != source_hash_before:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("source database changed during candidate build")
    args.output.unlink(missing_ok=True)
    temporary.replace(args.output)
    report = {
        "schema_version": 1,
        "source_database": str(source),
        "source_database_sha256": source_hash_before,
        "candidate_database": str(args.output.resolve()),
        "candidate_database_sha256": file_sha256(args.output),
        "proposals": str(args.proposals.resolve()),
        "counts": dict(sorted(counts.items())),
        "source_database_mutated": False,
        "promotion_applied_to_candidate": True,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
