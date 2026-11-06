"""Build source- and school-level completeness ledgers for the math archive.

This is an audit-only derivative.  It never changes the preserved Schoolinfo
attachments or the publish database.  The ledger reconciles the school roster,
attachment manifest, reconciled text extraction, math evidence index, strict
catalog, detail database, and the conservative publication gate.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PUBLIC_EXTRACTION_STATUS = "bounded"
PUBLIC_TITLE_BASES = {"table", "heading"}
NON_INSTRUCTION_ASSESSMENT_NAME_MARKERS = (
    "학업성적관리",
    "학업성적규정",
    "학업관리규정",
    "성적관리규정",
    "학교규정집",
    "학칙규정집",
)


def compact_join(values: Iterable[str]) -> str:
    return "|".join(sorted({value.strip() for value in values if value and value.strip()}))


def read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc


def source_path(record: dict[str, object]) -> str:
    source = record.get("source") or {}
    if not isinstance(source, dict):
        return ""
    return str(source.get("saved_path") or "").replace("\\", "/")


def source_school_code(record: dict[str, object]) -> str:
    source = record.get("source") or {}
    if not isinstance(source, dict):
        return ""
    return str(source.get("school_code") or "").strip()


@dataclass
class SourceAudit:
    source_indexed: bool = False
    recovery_scanned: bool = False
    extraction_status: str = "not_indexed"
    extraction_method: str = ""
    char_count: int = 0
    sha256: str = ""
    detected_subjects: set[str] = field(default_factory=set)
    evidence_subjects: set[str] = field(default_factory=set)
    evidence_records: int = 0
    strict_subjects: set[str] = field(default_factory=set)
    strict_records: int = 0
    db_cases: int = 0
    bounded_cases: int = 0
    bundle_review_cases: int = 0
    assessment_items: int = 0
    public_items: int = 0
    review_items: int = 0
    source_mismatch_items: int = 0
    unresolved_title_cases: int = 0


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--schools", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reconciled-source", type=Path)
    parser.add_argument("--evidence-index", type=Path)
    parser.add_argument("--recovery-scan", type=Path)
    parser.add_argument("--recovery-evidence-index", type=Path)
    parser.add_argument("--strict-index", type=Path)
    parser.add_argument("--recovery-strict-index", type=Path)
    parser.add_argument("--detail-database", type=Path)
    parser.add_argument("--expected-detail-cases", type=int)
    parser.add_argument("--expected-detail-items", type=int)
    parser.add_argument("--expected-public-items", type=int)
    parser.add_argument("--source-output", type=Path)
    parser.add_argument("--school-output", type=Path)
    parser.add_argument("--priority-output", type=Path)
    parser.add_argument("--failed-format-queue-output", type=Path)
    parser.add_argument("--unindexed-queue-output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    return parser.parse_args()


def configured_paths(args: argparse.Namespace) -> dict[str, Path]:
    root = args.project_root.resolve()
    derived = root / "data" / "derived"
    publish = root / "data" / "publish"
    return {
        "root": root,
        "schools": args.schools or derived / "schoolinfo_schools.csv",
        "manifest": args.manifest or derived / "math_assessment_source_manifest.csv",
        "reconciled": args.reconciled_source or derived / "math_assessment_generic_reconciled.jsonl",
        "evidence": args.evidence_index or derived / "math_assessment_all_subject_evidence_v2_index.jsonl",
        "recovery_scan": args.recovery_scan
        or derived / "math_assessment_unindexed_plan_candidate_scan.jsonl",
        "recovery_evidence": args.recovery_evidence_index
        or derived / "math_assessment_unindexed_recovery_v1_index.jsonl",
        "strict": args.strict_index or derived / "math_assessment_strict_all_subjects_v2.jsonl",
        "recovery_strict": args.recovery_strict_index
        or derived / "math_assessment_unindexed_recovery_v1_strict.jsonl",
        "database": args.detail_database or publish / "math_assessment_catalog_detail.sqlite",
        "source_output": args.source_output or derived / "math_assessment_source_completeness_ledger.csv",
        "school_output": args.school_output or derived / "math_assessment_school_completeness_ledger.csv",
        "priority_output": args.priority_output or derived / "math_assessment_recovery_priority_queue.csv",
        "failed_format_queue_output": args.failed_format_queue_output
        or derived / "math_assessment_failed_format_recovery_queue.csv",
        "unindexed_queue_output": args.unindexed_queue_output
        or derived / "math_assessment_unindexed_plan_candidate_queue.jsonl",
        "summary_output": args.summary_output or derived / "math_assessment_completeness_summary.json",
    }


def load_roster(path: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_code: dict[str, dict[str, str]] = {}
    ledger_keys: set[str] = set()
    for row in rows:
        code = (row.get("school_code") or "").strip()
        ledger_key = code or (row.get("school_id") or "").strip()
        if not ledger_key:
            raise ValueError(f"school roster row without a stable identifier: {row}")
        if ledger_key in ledger_keys:
            raise ValueError(f"duplicate school identity in roster: {ledger_key}")
        ledger_keys.add(ledger_key)
        row["_ledger_key"] = ledger_key
        if code:
            if code in by_code:
                raise ValueError(f"duplicate school_code in roster: {code}")
            by_code[code] = row
    return rows, by_code


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    seen: set[str] = set()
    for row in rows:
        saved_path = (row.get("saved_path") or "").replace("\\", "/")
        if not saved_path:
            raise ValueError("manifest row without saved_path")
        if saved_path in seen:
            raise ValueError(f"duplicate saved_path in manifest: {saved_path}")
        seen.add(saved_path)
        row["saved_path"] = saved_path
    return rows


def load_source_audits(path: Path) -> tuple[dict[str, SourceAudit], dict[tuple[str, str], str], collections.Counter[str]]:
    audits: dict[str, SourceAudit] = {}
    sha_school_to_path: dict[tuple[str, str], str] = {}
    status_counts: collections.Counter[str] = collections.Counter()
    for record in read_jsonl(path):
        saved_path = source_path(record)
        if not saved_path:
            raise ValueError("reconciled source row without saved_path")
        if saved_path in audits:
            raise ValueError(f"duplicate reconciled source row: {saved_path}")
        status = str(record.get("final_status") or record.get("extract_status") or "unknown")
        subjects: set[str] = set()
        for hit in record.get("subject_hits") or []:
            if isinstance(hit, dict) and hit.get("subject"):
                subjects.add(str(hit["subject"]).strip())
        audit = SourceAudit(
            source_indexed=True,
            extraction_status=status,
            extraction_method=str(record.get("extraction_method") or ""),
            char_count=int(record.get("char_count") or 0),
            sha256=str(record.get("sha256") or ""),
            detected_subjects=subjects,
        )
        audits[saved_path] = audit
        status_counts[status] += 1
        key = (audit.sha256, source_school_code(record))
        if audit.sha256 and key not in sha_school_to_path:
            sha_school_to_path[key] = saved_path
    return audits, sha_school_to_path, status_counts


def apply_recovery_scan(
    path: Path,
    audits: dict[str, SourceAudit],
    sha_school_to_path: dict[tuple[str, str], str],
) -> tuple[int, collections.Counter[str], int]:
    if not path.is_file():
        return 0, collections.Counter(), 0
    rows = hit_rows = 0
    statuses: collections.Counter[str] = collections.Counter()
    for record in read_jsonl(path):
        rows += 1
        saved_path = source_path(record)
        if not saved_path:
            raise ValueError("recovery scan row without saved_path")
        audit = audits.setdefault(saved_path, SourceAudit())
        audit.recovery_scanned = True
        status = str(record.get("extract_status") or "unknown")
        statuses[status] += 1
        if not audit.source_indexed:
            audit.extraction_status = status
            audit.extraction_method = "unindexed_recovery_scan"
            audit.char_count = int(record.get("char_count") or 0)
            audit.sha256 = str(record.get("sha256") or "")
        subjects: set[str] = set()
        for hit in record.get("subject_hits") or []:
            if isinstance(hit, dict) and hit.get("subject"):
                subjects.add(str(hit["subject"]).strip())
        if subjects:
            hit_rows += 1
            audit.detected_subjects.update(subjects)
        key = (str(record.get("sha256") or ""), source_school_code(record))
        if key[0] and key not in sha_school_to_path:
            sha_school_to_path[key] = saved_path
    return rows, statuses, hit_rows


def add_index_counts(path: Path, audits: dict[str, SourceAudit], *, strict: bool) -> tuple[int, int]:
    rows = missing_sources = 0
    for record in read_jsonl(path):
        rows += 1
        saved_path = source_path(record)
        audit = audits.get(saved_path)
        if audit is None:
            missing_sources += 1
            audit = audits.setdefault(saved_path, SourceAudit())
        subject = str(record.get("subject") or "").strip()
        if strict:
            audit.strict_records += 1
            if subject:
                audit.strict_subjects.add(subject)
        else:
            audit.evidence_records += 1
            if subject:
                audit.evidence_subjects.add(subject)
    return rows, missing_sources


def add_database_counts(
    path: Path,
    audits: dict[str, SourceAudit],
    sha_school_to_path: dict[tuple[str, str], str],
) -> tuple[int, int, int, int]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT cases.source_sha256, cases.school_code, cases.case_id, cases.title_basis,
               detail.extraction_status AS case_status,
               COUNT(items.item_id) AS item_count,
               SUM(items.extraction_status = 'bounded'
                   AND items.title_basis IN ('table', 'heading')) AS public_items,
               SUM(NOT (items.extraction_status = 'bounded'
                   AND items.title_basis IN ('table', 'heading'))) AS review_items,
               SUM(items.extraction_status = 'source_mismatch_review') AS mismatch_items
        FROM cases
        JOIN case_detail_status detail ON detail.case_id = cases.case_id
        JOIN assessment_items items ON items.case_id = cases.case_id
        GROUP BY cases.case_id
        ORDER BY cases.case_id
        """
    ).fetchall()
    total_items = public_items = unmapped_cases = 0
    for row in rows:
        key = (str(row["source_sha256"] or ""), str(row["school_code"] or ""))
        saved_path = sha_school_to_path.get(key)
        if not saved_path:
            unmapped_cases += 1
            continue
        audit = audits[saved_path]
        audit.db_cases += 1
        audit.assessment_items += int(row["item_count"] or 0)
        audit.public_items += int(row["public_items"] or 0)
        audit.review_items += int(row["review_items"] or 0)
        audit.source_mismatch_items += int(row["mismatch_items"] or 0)
        if str(row["case_status"]) == "bounded":
            audit.bounded_cases += 1
        else:
            audit.bundle_review_cases += 1
        if str(row["title_basis"]) != "source_detail":
            audit.unresolved_title_cases += 1
        total_items += int(row["item_count"] or 0)
        public_items += int(row["public_items"] or 0)
    connection.close()
    return len(rows), total_items, public_items, unmapped_cases


def manifest_scope(candidate_name: str, audit: SourceAudit) -> str:
    if audit.source_indexed:
        return "instruction_assessment_candidate"
    if audit.recovery_scanned:
        return "recovery_scanned_plan_candidate"
    normalized = "".join(candidate_name.split())
    if any(marker in normalized for marker in NON_INSTRUCTION_ASSESSMENT_NAME_MARKERS):
        return "excluded_non_instruction_assessment"
    return "unindexed_plan_candidate"


def classify_source(
    audit: SourceAudit, *, file_exists: bool, scope: str
) -> tuple[str, str, str]:
    reasons: list[str] = []
    if not file_exists:
        reasons.append("local_source_missing")
    if not audit.source_indexed and scope == "unindexed_plan_candidate":
        reasons.append("not_in_reconciled_source_index")
    elif (
        audit.recovery_scanned
        and audit.detected_subjects
        and not audit.evidence_records
    ):
        reasons.append("recovered_math_hit_pending_integration")
    elif audit.recovery_scanned and audit.extraction_status == "failed":
        reasons.append("recovery_extraction_failed")
    elif audit.recovery_scanned:
        reasons.append("recovery_scan_no_math_hit")
    elif scope == "excluded_non_instruction_assessment":
        reasons.append("filename_non_instruction_assessment")
    if audit.extraction_status == "failed":
        reasons.append("extraction_failed")
    elif audit.extraction_status == "short":
        reasons.append("extraction_short")
    if (audit.source_indexed or audit.recovery_scanned) and not audit.detected_subjects:
        reasons.append("no_math_subject_hit")
    if audit.evidence_records and not audit.strict_records:
        reasons.append("math_evidence_not_strict")
    if audit.bundle_review_cases:
        reasons.append("assessment_boundary_review")
    if audit.source_mismatch_items:
        reasons.append("subject_mismatch_review")
    if audit.unresolved_title_cases:
        reasons.append("title_not_source_bounded")

    if scope == "excluded_non_instruction_assessment":
        state = "excluded_non_instruction_assessment"
    elif audit.public_items:
        state = "public_confirmed"
    elif audit.db_cases:
        state = "strict_analysis_review"
    elif audit.evidence_records:
        state = "math_evidence_only"
    elif audit.recovery_scanned and audit.detected_subjects and not audit.evidence_records:
        state = "recovered_math_hit_pending_integration"
    elif audit.recovery_scanned and not audit.source_indexed:
        state = "recovery_scanned_no_math"
    elif audit.detected_subjects:
        state = "math_subject_hit_only"
    elif audit.source_indexed:
        state = "indexed_no_math_signal"
    else:
        state = "manifest_not_indexed"

    if scope == "unindexed_plan_candidate" or audit.extraction_status == "failed":
        priority = "P0"
    elif audit.recovery_scanned and audit.detected_subjects and not audit.evidence_records:
        priority = "P1"
    elif audit.extraction_status == "short" or audit.source_mismatch_items:
        priority = "P1"
    elif audit.bundle_review_cases or audit.unresolved_title_cases:
        priority = "P2"
    elif audit.evidence_records and not audit.strict_records:
        priority = "P3"
    else:
        priority = ""
    return state, priority, "|".join(reasons)


SOURCE_FIELDS = [
    "school_code", "school_name", "region", "district", "candidate_name", "manifest_scope",
    "saved_path", "source_url", "file_exists", "manifest_size_bytes",
    "source_indexed", "recovery_scanned", "extraction_status", "extraction_method", "char_count",
    "detected_subjects", "evidence_subjects", "strict_subjects",
    "evidence_records", "strict_records", "db_cases", "bounded_cases",
    "bundle_review_cases", "assessment_items", "public_items", "review_items",
    "source_mismatch_items", "unresolved_title_cases", "publication_state",
    "recovery_priority", "blocking_reasons",
]

FAILED_FORMAT_FIELDS = SOURCE_FIELDS + ["source_format", "recovery_route"]


def source_ledger_rows(
    manifest_rows: list[dict[str, str]],
    roster: dict[str, dict[str, str]],
    audits: dict[str, SourceAudit],
    root: Path,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for manifest in manifest_rows:
        code = (manifest.get("school_code") or "").strip()
        school = roster.get(code, {})
        saved_path = manifest["saved_path"]
        audit = audits.get(saved_path, SourceAudit())
        local_path = root / saved_path
        file_exists = local_path.is_file()
        scope = manifest_scope(manifest.get("candidate_name", ""), audit)
        state, priority, reasons = classify_source(audit, file_exists=file_exists, scope=scope)
        output.append(
            {
                "school_code": code,
                "school_name": manifest.get("school_name") or school.get("school_name", ""),
                "region": school.get("region_sido") or school.get("region") or "",
                "district": school.get("region_sgg") or school.get("district") or "",
                "candidate_name": manifest.get("candidate_name", ""),
                "manifest_scope": scope,
                "saved_path": saved_path,
                "source_url": manifest.get("source_url", ""),
                "file_exists": str(file_exists).lower(),
                "manifest_size_bytes": manifest.get("size_bytes", ""),
                "source_indexed": str(audit.source_indexed).lower(),
                "recovery_scanned": str(audit.recovery_scanned).lower(),
                "extraction_status": audit.extraction_status,
                "extraction_method": audit.extraction_method,
                "char_count": audit.char_count,
                "detected_subjects": compact_join(audit.detected_subjects),
                "evidence_subjects": compact_join(audit.evidence_subjects),
                "strict_subjects": compact_join(audit.strict_subjects),
                "evidence_records": audit.evidence_records,
                "strict_records": audit.strict_records,
                "db_cases": audit.db_cases,
                "bounded_cases": audit.bounded_cases,
                "bundle_review_cases": audit.bundle_review_cases,
                "assessment_items": audit.assessment_items,
                "public_items": audit.public_items,
                "review_items": audit.review_items,
                "source_mismatch_items": audit.source_mismatch_items,
                "unresolved_title_cases": audit.unresolved_title_cases,
                "publication_state": state,
                "recovery_priority": priority,
                "blocking_reasons": reasons,
            }
        )
    return output


SCHOOL_FIELDS = [
    "school_code", "school_name", "region", "district", "school_type",
    "manifest_attachments", "indexed_attachments", "extraction_ok",
    "extraction_short", "extraction_failed", "not_indexed_attachments",
    "unindexed_plan_candidates", "excluded_non_instruction_attachments",
    "detected_subjects", "evidence_subjects", "strict_subjects", "strict_cases",
    "bounded_cases", "bundle_review_cases", "assessment_items", "public_items",
    "review_items", "source_mismatch_items", "unresolved_title_cases",
    "school_publication_state", "highest_recovery_priority", "blocking_reasons",
]


def school_ledger_rows(
    roster_rows: list[dict[str, str]], source_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    by_school: dict[str, list[dict[str, object]]] = collections.defaultdict(list)
    for row in source_rows:
        by_school[str(row["school_code"])].append(row)
    output: list[dict[str, object]] = []
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "": 9}
    for school in roster_rows:
        code = school["school_code"].strip()
        ledger_key = school["_ledger_key"]
        sources = by_school.get(code, []) if code else []
        detected = set()
        evidence = set()
        strict = set()
        reasons = set()
        for source in sources:
            detected.update(str(source["detected_subjects"]).split("|"))
            evidence.update(str(source["evidence_subjects"]).split("|"))
            strict.update(str(source["strict_subjects"]).split("|"))
            reasons.update(str(source["blocking_reasons"]).split("|"))
        detected.discard(""); evidence.discard(""); strict.discard(""); reasons.discard("")
        public_items = sum(int(row["public_items"]) for row in sources)
        strict_cases = sum(int(row["db_cases"]) for row in sources)
        evidence_records = sum(int(row["evidence_records"]) for row in sources)
        indexed = sum(str(row["source_indexed"]) == "true" for row in sources)
        recovery_scanned = sum(str(row["recovery_scanned"]) == "true" for row in sources)
        unindexed_plan_candidates = sum(
            str(row["manifest_scope"]) == "unindexed_plan_candidate" for row in sources
        )
        excluded_non_instruction = sum(
            str(row["manifest_scope"]) == "excluded_non_instruction_assessment" for row in sources
        )
        if public_items:
            state = "public_confirmed"
        elif strict_cases:
            state = "strict_analysis_review"
        elif evidence_records:
            state = "math_evidence_only"
        elif indexed or recovery_scanned:
            state = "collected_no_confirmed_math"
        elif unindexed_plan_candidates:
            state = "attachments_not_indexed"
        elif sources and excluded_non_instruction == len(sources):
            state = "no_instruction_assessment_attachment"
        else:
            state = "no_manifest_attachment"
        priorities = [str(row["recovery_priority"]) for row in sources]
        highest = min(priorities or [""], key=lambda value: priority_order.get(value, 8))
        output.append(
            {
                "school_code": code or ledger_key,
                "school_name": school.get("school_name", ""),
                "region": school.get("region_sido") or school.get("region") or "",
                "district": school.get("region_sgg") or school.get("district") or "",
                "school_type": school.get("school_type", ""),
                "manifest_attachments": len(sources),
                "indexed_attachments": indexed,
                "extraction_ok": sum(str(row["extraction_status"]) == "ok" for row in sources),
                "extraction_short": sum(str(row["extraction_status"]) == "short" for row in sources),
                "extraction_failed": sum(str(row["extraction_status"]) == "failed" for row in sources),
                "not_indexed_attachments": sum(
                    str(row["source_indexed"]) != "true"
                    and str(row["recovery_scanned"]) != "true"
                    for row in sources
                ),
                "unindexed_plan_candidates": unindexed_plan_candidates,
                "excluded_non_instruction_attachments": excluded_non_instruction,
                "detected_subjects": compact_join(detected),
                "evidence_subjects": compact_join(evidence),
                "strict_subjects": compact_join(strict),
                "strict_cases": strict_cases,
                "bounded_cases": sum(int(row["bounded_cases"]) for row in sources),
                "bundle_review_cases": sum(int(row["bundle_review_cases"]) for row in sources),
                "assessment_items": sum(int(row["assessment_items"]) for row in sources),
                "public_items": public_items,
                "review_items": sum(int(row["review_items"]) for row in sources),
                "source_mismatch_items": sum(int(row["source_mismatch_items"]) for row in sources),
                "unresolved_title_cases": sum(int(row["unresolved_title_cases"]) for row in sources),
                "school_publication_state": state,
                "highest_recovery_priority": highest,
                "blocking_reasons": compact_join(reasons),
            }
        )
    return output


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    paths = configured_paths(args)
    for key in ("schools", "manifest", "reconciled", "evidence", "strict", "database"):
        if not paths[key].is_file():
            raise SystemExit(f"missing required input: {paths[key]}")

    roster_rows, roster = load_roster(paths["schools"])
    manifest_rows = load_manifest(paths["manifest"])
    audits, sha_school_to_path, extraction_status = load_source_audits(paths["reconciled"])
    canonical_source_paths = set(audits)
    recovery_rows, recovery_status, recovery_hit_rows = apply_recovery_scan(
        paths["recovery_scan"], audits, sha_school_to_path
    )
    evidence_rows, evidence_unmapped = add_index_counts(paths["evidence"], audits, strict=False)
    recovery_evidence_rows = recovery_evidence_unmapped = 0
    if paths["recovery_evidence"].is_file():
        recovery_evidence_rows, recovery_evidence_unmapped = add_index_counts(
            paths["recovery_evidence"], audits, strict=False
        )
    strict_rows, strict_unmapped = add_index_counts(paths["strict"], audits, strict=True)
    recovery_strict_rows = recovery_strict_unmapped = 0
    if paths["recovery_strict"].is_file():
        recovery_strict_rows, recovery_strict_unmapped = add_index_counts(
            paths["recovery_strict"], audits, strict=True
        )
    db_cases, db_items, db_public_items, db_unmapped = add_database_counts(
        paths["database"], audits, sha_school_to_path
    )

    sources = source_ledger_rows(manifest_rows, roster, audits, paths["root"])
    schools = school_ledger_rows(roster_rows, sources)
    priority_rows = [row for row in sources if row["recovery_priority"]]
    priority_rows.sort(
        key=lambda row: (
            str(row["recovery_priority"]),
            -int(row["source_mismatch_items"]),
            -int(row["bundle_review_cases"]),
            str(row["region"]),
            str(row["school_name"]),
            str(row["saved_path"]),
        )
    )

    write_csv(paths["source_output"], SOURCE_FIELDS, sources)
    write_csv(paths["school_output"], SCHOOL_FIELDS, schools)
    write_csv(paths["priority_output"], SOURCE_FIELDS, priority_rows)
    failed_format_rows: list[dict[str, object]] = []
    for row in sources:
        if str(row["extraction_status"]) != "failed":
            continue
        failed = dict(row)
        suffix = Path(str(row["candidate_name"]) or str(row["saved_path"])).suffix.lower()
        if suffix == ".pdf":
            route = "ocr_required"
        elif suffix in {".zip", ".hwpx"}:
            route = "archive_integrity_or_alternate_converter"
        elif suffix == ".hwp":
            route = "binary_hwp_alternate_converter"
        else:
            route = "manual_format_review"
        failed["source_format"] = suffix.lstrip(".") or "unknown"
        failed["recovery_route"] = route
        failed_format_rows.append(failed)
    write_csv(
        paths["failed_format_queue_output"],
        FAILED_FORMAT_FIELDS,
        failed_format_rows,
    )
    manifest_by_path = {row["saved_path"]: row for row in manifest_rows}
    unindexed_rows = [
        row for row in sources if row["manifest_scope"] == "unindexed_plan_candidate"
    ]
    with paths["unindexed_queue_output"].open("w", encoding="utf-8", newline="\n") as handle:
        for row in unindexed_rows:
            handle.write(
                json.dumps(
                    {
                        "source": manifest_by_path[str(row["saved_path"])],
                        "final_status": "not_indexed",
                        "recovery_reason": "unindexed_plan_candidate",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    source_states = collections.Counter(str(row["publication_state"]) for row in sources)
    school_states = collections.Counter(str(row["school_publication_state"]) for row in schools)
    priorities = collections.Counter(str(row["recovery_priority"]) for row in priority_rows)
    manifest_paths = {row["saved_path"] for row in manifest_rows}
    roster_codes = set(roster)
    roster_ledger_keys = {row["_ledger_key"] for row in roster_rows}
    manifest_codes = {(row.get("school_code") or "").strip() for row in manifest_rows}
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "unit_notes": {
            "source": "one Schoolinfo attachment manifest row",
            "school": "one current high-school roster row",
            "public": "bounded assessment item with a table or heading source title",
            "warning": "No math signal in collected plans is not proof that a course was not offered.",
        },
        "counts": {
            "roster_schools": len(roster_rows),
            "roster_schools_without_school_code": sum(
                not (row.get("school_code") or "").strip() for row in roster_rows
            ),
            "manifest_attachments": len(manifest_rows),
            "manifest_school_codes": len(manifest_codes - {""}),
            "reconciled_source_rows": len(canonical_source_paths),
            "reconciled_extraction_status": dict(sorted(extraction_status.items())),
            "recovery_scan_rows": recovery_rows,
            "recovery_scan_status": dict(sorted(recovery_status.items())),
            "recovery_scan_math_hit_rows": recovery_hit_rows,
            "evidence_rows": evidence_rows,
            "recovery_evidence_rows": recovery_evidence_rows,
            "strict_rows": strict_rows,
            "recovery_strict_rows": recovery_strict_rows,
            "detail_cases": db_cases,
            "detail_items": db_items,
            "public_items": db_public_items,
            "source_publication_states": dict(sorted(source_states.items())),
            "school_publication_states": dict(sorted(school_states.items())),
            "recovery_priorities": dict(sorted(priorities.items())),
        },
        "reconciliation": {
            "roster_without_manifest": sum(
                not (row.get("school_code") or "").strip()
                or (row.get("school_code") or "").strip() not in manifest_codes
                for row in roster_rows
            ),
            "manifest_school_codes_outside_roster": len(manifest_codes - roster_codes - {""}),
            "manifest_rows_not_in_canonical_index": sum(
                row["saved_path"] not in canonical_source_paths for row in manifest_rows
            ),
            "manifest_rows_not_scanned_or_indexed": sum(
                row["saved_path"] not in audits for row in manifest_rows
            ),
            "reconciled_rows_outside_manifest": len(set(audits) - manifest_paths),
            "evidence_rows_without_reconciled_source": evidence_unmapped,
            "recovery_evidence_rows_without_recovery_source": recovery_evidence_unmapped,
            "strict_rows_without_reconciled_source": strict_unmapped,
            "recovery_strict_rows_without_recovery_source": recovery_strict_unmapped,
            "detail_cases_without_source_mapping": db_unmapped,
        },
        "checks": {
            "roster_school_identities_unique": len(roster_rows) == len(roster_ledger_keys),
            "manifest_saved_paths_unique": len(manifest_rows) == len(manifest_paths),
            "all_local_manifest_files_present": all(row["file_exists"] == "true" for row in sources),
            "detail_case_count_reconciles": db_cases
            == (args.expected_detail_cases or strict_rows + recovery_strict_rows),
            "detail_item_count_reconciles": (
                db_items == args.expected_detail_items
                if args.expected_detail_items is not None
                else db_items >= db_public_items
            ),
            "public_item_count_reconciles": (
                db_public_items == args.expected_public_items
                if args.expected_public_items is not None
                else db_public_items > 0
            ),
        },
        "outputs": {
            "source_ledger": str(paths["source_output"]),
            "school_ledger": str(paths["school_output"]),
            "priority_queue": str(paths["priority_output"]),
            "failed_format_recovery_queue": str(paths["failed_format_queue_output"]),
            "unindexed_plan_candidate_queue": str(paths["unindexed_queue_output"]),
        },
    }
    paths["summary_output"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
