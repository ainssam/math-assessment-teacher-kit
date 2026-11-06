"""Audit a candidate DB produced by explicit-item recovery before release."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from pathlib import Path

from audit_math_assessment_table_structure import (
    audit_html,
    restore_escaped_table_rows,
)
from audit_math_assessment_titles_full import audit_flags, confidence
from audit_unresolved_math_assessment_titles import (
    SUPPORT_MARKER_RE,
    layout_text,
    standard_alignment,
)
from package_math_assessment_vercel_data import assert_bounded_html_privacy
from propose_math_assessment_explicit_item_recovery import (
    BLOCKING_TABLE_FLAGS,
    STRONG_BOUNDARIES,
    competing_direct_candidates,
    source_course_identity_evidence,
    title_key,
    unique_direct_candidates,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-database",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "publish"
        / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--candidate-database",
        type=Path,
        default=PROJECT_ROOT
        / ".tmp"
        / "math_assessment_catalog_detail_explicit_recovery.sqlite",
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
        / "data"
        / "derived"
        / "math_assessment_explicit_item_recovery_candidate_audit.json",
    )
    return parser.parse_args()


def accepted_proposals(path: Path) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"proposal row must be object: {path}:{line_number}")
            if row.get("decision") != "accepted":
                continue
            item_id = str(row.get("item_id") or "")
            if not item_id or item_id in output:
                raise ValueError(f"duplicate or empty accepted item: {path}:{line_number}")
            output[item_id] = row
    return output


def scalar(connection: sqlite3.Connection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def duplicate_public_title_count(connection: sqlite3.Connection) -> int:
    grouped: defaultdict[tuple[str, str], int] = defaultdict(int)
    for case_id, title in connection.execute(
        """
        SELECT case_id, title FROM assessment_items
        WHERE extraction_status = 'bounded'
          AND title_basis IN ('table', 'heading')
        """
    ):
        grouped[(str(case_id), title_key(str(title)))] += 1
    return sum(count - 1 for count in grouped.values() if count > 1)


def main() -> None:
    args = parse_args()
    proposals = accepted_proposals(args.proposals)
    source = sqlite3.connect(
        f"file:{args.source_database.resolve()}?mode=ro", uri=True
    )
    candidate = sqlite3.connect(
        f"file:{args.candidate_database.resolve()}?mode=ro", uri=True
    )
    source.row_factory = sqlite3.Row
    candidate.row_factory = sqlite3.Row

    checks: dict[str, bool] = {}
    counts: Counter[str] = Counter()
    failures: list[dict[str, object]] = []
    source_items = scalar(source, "SELECT COUNT(*) FROM assessment_items")
    candidate_items = scalar(candidate, "SELECT COUNT(*) FROM assessment_items")
    source_bounded = scalar(
        source,
        "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'",
    )
    candidate_bounded = scalar(
        candidate,
        "SELECT COUNT(*) FROM assessment_items WHERE extraction_status = 'bounded'",
    )
    checks["item_count_unchanged"] = source_items == candidate_items
    checks["bounded_delta_matches"] = (
        candidate_bounded - source_bounded == len(proposals)
    )
    checks["no_new_public_title_duplicates"] = (
        duplicate_public_title_count(candidate)
        == duplicate_public_title_count(source)
    )

    for item_id, proposal in proposals.items():
        row = candidate.execute(
            """
            SELECT item.*, cases.subject, status.boundary_status
            FROM assessment_items AS item
            JOIN cases USING (case_id)
            JOIN case_detail_status AS status USING (case_id)
            WHERE item.item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            failures.append({"item_id": item_id, "reason": "missing_candidate_item"})
            continue
        source_html = restore_escaped_table_rows(
            zlib.decompress(bytes(row["source_html_zlib"])).decode(
                "utf-8", errors="replace"
            )
        )
        text = layout_text(source_html)
        direct = unique_direct_candidates(text)
        key = title_key(str(row["title"]))
        direct_matches = [
            value for value in direct if title_key(str(value["title"])) == key
        ]
        competing = competing_direct_candidates(str(row["title"]), direct)
        alignment = standard_alignment(text, str(row["subject"]))
        support_markers = len(
            {match.group(0) for match in SUPPORT_MARKER_RE.finditer(text)}
        )
        title_confidence = confidence(
            audit_flags(str(row["title"]), str(row["title_basis"])),
            str(row["title_basis"]),
            explicit_source_label=True,
        )
        table_flags = set(str(flag) for flag in audit_html(source_html)["flags"])
        item_checks = {
            "bounded": str(row["extraction_status"]) == "bounded",
            "table_title_basis": str(row["title_basis"]) == "table",
            "strong_subject_boundary": str(row["boundary_status"])
            in STRONG_BOUNDARIES,
            "source_hash_unchanged": hashlib.sha256(
                source_html.encode("utf-8")
            ).hexdigest()
            == str(proposal["source_html_sha256"]),
            "single_direct_title": not competing,
            "exact_direct_title_match": len(direct_matches) == 1,
            "direct_table_row": bool(
                direct_matches and direct_matches[0]["detection"] == "table_row"
            ),
            "source_course_identity_evidence": source_course_identity_evidence(
                alignment=alignment,
                title=str(row["title"]),
                subject=str(row["subject"]),
            ),
            "assessment_support_markers": support_markers >= 2,
            "title_not_rejected": title_confidence != "reject",
            "single_assessment_structure": not bool(
                table_flags.intersection(BLOCKING_TABLE_FLAGS)
            ),
        }
        failed = [name for name, passed in item_checks.items() if not passed]
        if failed:
            failures.append(
                {"item_id": item_id, "title": str(row["title"]), "failed": failed}
            )
        else:
            counts["items_verified"] += 1

    source.close()
    candidate.close()
    try:
        assert_bounded_html_privacy(args.candidate_database)
        checks["bounded_html_privacy_gate"] = True
    except RuntimeError as error:
        checks["bounded_html_privacy_gate"] = False
        failures.append({"reason": "privacy_gate", "detail": str(error)})
    checks["all_promoted_items_verified"] = not failures
    checks["integrity_ok"] = (
        sqlite3.connect(args.candidate_database)
        .execute("PRAGMA integrity_check")
        .fetchone()[0]
        == "ok"
    )
    all_checks_passed = all(checks.values())
    report = {
        "schema_version": 1,
        "source_database": str(args.source_database.resolve()),
        "candidate_database": str(args.candidate_database.resolve()),
        "accepted_proposals": len(proposals),
        "source_items": source_items,
        "candidate_items": candidate_items,
        "source_bounded_items": source_bounded,
        "candidate_bounded_items": candidate_bounded,
        "counts": dict(sorted(counts.items())),
        "checks": checks,
        "all_checks_passed": all_checks_passed,
        "failure_count": len(failures),
        "failures": failures[:100],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    if not all_checks_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
