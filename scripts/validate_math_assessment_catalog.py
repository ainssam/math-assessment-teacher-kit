"""Validate row counts, keys, statuses, and referential integrity of final outputs."""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import tempfile
from pathlib import Path

from build_school_subject_assessment_catalog import SUBJECTS


ALLOWED_COVERAGE = {
    "found", "found_curriculum_ambiguous", "extraction_failed",
    "not_found_in_collected_plans", "offering_unknown",
}


def scan_jsonl(path: Path, key_fn) -> tuple[int, int, set[object], collections.Counter[str]]:
    rows = bad = 0
    keys: set[object] = set()
    statuses: collections.Counter[str] = collections.Counter()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows += 1
            keys.add(key_fn(record))
            if "extract_status" in record:
                statuses[str(record.get("extract_status") or "unknown")] += 1
    return rows, bad, keys, statuses


def source_identity(record: dict[str, object]) -> str:
    source = record.get("source") or {}
    return str(source.get("saved_path") or source.get("final_url") or "")


def subject_identity(record: dict[str, object]) -> tuple[str, str, str]:
    return source_identity(record), str(record.get("curriculum_hint") or ""), str(record.get("subject") or "")


def catalog_identity(record: dict[str, object]) -> tuple[str, str, str]:
    return source_identity(record), str(record.get("resolved_curriculum") or ""), str(record.get("subject") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schools", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, required=True)
    parser.add_argument("--strict-index", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-source-rows", type=int, default=0)
    args = parser.parse_args()

    school_keys: set[str] = set()
    with args.schools.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = str(row.get("school_code") or row.get("school_name") or "")
            if key:
                school_keys.add(key)

    source_rows, source_bad, source_keys, source_status = scan_jsonl(args.source_index, source_identity)
    evidence_rows, evidence_bad, evidence_keys, evidence_status = scan_jsonl(args.evidence_index, subject_identity)
    strict_rows, strict_bad, strict_keys, strict_status = scan_jsonl(args.strict_index, subject_identity)
    catalog_rows, catalog_bad, catalog_keys, catalog_status = scan_jsonl(args.catalog, catalog_identity)

    coverage_rows = 0
    coverage_keys: set[tuple[str, str, str]] = set()
    coverage_schools: set[str] = set()
    coverage_status: collections.Counter[str] = collections.Counter()
    with args.coverage.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            coverage_rows += 1
            key = (str(row.get("school_code") or ""), str(row.get("curriculum") or ""), str(row.get("subject") or ""))
            coverage_keys.add(key)
            coverage_schools.add(key[0])
            coverage_status[str(row.get("coverage_status") or "unknown")] += 1

    expected_coverage_rows = len(school_keys) * sum(len(values) for values in SUBJECTS.values())
    checks = {
        "source_json_valid": source_bad == 0,
        "source_count_matches_expected": args.expected_source_rows == 0 or source_rows == args.expected_source_rows,
        "source_keys_unique_and_nonempty": len(source_keys) == source_rows and "" not in source_keys,
        "evidence_json_valid": evidence_bad == 0,
        "evidence_keys_unique": len(evidence_keys) == evidence_rows,
        "evidence_sources_exist": {key[0] for key in evidence_keys}.issubset(source_keys),
        "strict_json_valid": strict_bad == 0,
        "strict_keys_unique": len(strict_keys) == strict_rows,
        "strict_is_subset_of_evidence": strict_keys.issubset(evidence_keys),
        "catalog_json_valid": catalog_bad == 0,
        "catalog_matches_strict_row_count": catalog_rows == strict_rows,
        "coverage_row_count": coverage_rows == expected_coverage_rows,
        "coverage_keys_unique": len(coverage_keys) == coverage_rows,
        "coverage_school_roster_matches": coverage_schools == school_keys,
        "coverage_statuses_valid": set(coverage_status).issubset(ALLOWED_COVERAGE),
        "coverage_statuses_reconcile": sum(coverage_status.values()) == coverage_rows,
    }
    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "schools": len(school_keys),
            "source_rows": source_rows,
            "source_unique_keys": len(source_keys),
            "source_bad_json": source_bad,
            "source_extract_status": dict(source_status),
            "evidence_rows": evidence_rows,
            "evidence_bad_json": evidence_bad,
            "strict_rows": strict_rows,
            "strict_bad_json": strict_bad,
            "catalog_rows": catalog_rows,
            "catalog_bad_json": catalog_bad,
            "coverage_rows": coverage_rows,
            "expected_coverage_rows": expected_coverage_rows,
            "coverage_status": dict(coverage_status),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.report.stem + "_", suffix=".partial", dir=args.report.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, args.report)
    print(json.dumps(report, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
