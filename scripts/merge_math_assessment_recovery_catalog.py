"""Merge a validated recovery catalogue into the base derived catalogue.

The two inputs remain untouched.  Coverage is recomputed cell by cell from
the disjoint source counts so that a newly found subject replaces a previous
``not_found`` or ``offering_unknown`` state without implying course offering.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path

from build_math_assessment_publish_db import case_identifier


STATUS_ORDER = (
    "found",
    "found_curriculum_ambiguous",
    "extraction_failed",
    "not_found_in_collected_plans",
    "offering_unknown",
)
COUNT_FIELDS = (
    "found_documents",
    "ambiguous_curriculum_documents",
    "explicit_subject_documents",
    "explicit_subject_incomplete",
    "school_extracted_ok",
    "school_extracted_short",
    "school_extracted_failed",
)


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON object required: {path}")
    return value


def catalog_identity(row: dict[str, object]) -> str:
    source = row.get("source")
    source = source if isinstance(source, dict) else {}
    source_sha = str(row.get("sha256") or source.get("sha256") or "")
    curriculum = str(row.get("resolved_curriculum") or "shared")
    subject = str(row.get("subject") or "").strip()
    if not source_sha or not subject:
        raise SystemExit("catalog row missing source hash or subject")
    return case_identifier(source_sha, curriculum, subject)


def read_catalog(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"malformed JSONL {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"JSON object required {path}:{line_number}")
            yield row


def load_coverage(path: Path) -> tuple[list[str], dict[tuple[str, str, str], dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in reader:
            key = (
                str(row.get("school_code") or ""),
                str(row.get("curriculum") or ""),
                str(row.get("subject") or ""),
            )
            if not all(key) or key in rows:
                raise SystemExit(f"invalid or duplicate coverage key {key} in {path}")
            rows[key] = dict(row)
    return fields, rows


def integer(row: dict[str, str], field: str) -> int:
    try:
        return int(row.get(field) or 0)
    except ValueError as exc:
        raise SystemExit(f"invalid coverage integer {field}={row.get(field)!r}") from exc


def merged_status(row: dict[str, str]) -> str:
    if integer(row, "found_documents"):
        return "found"
    if integer(row, "ambiguous_curriculum_documents"):
        return "found_curriculum_ambiguous"
    if integer(row, "explicit_subject_incomplete"):
        return "extraction_failed"
    if integer(row, "school_extracted_ok"):
        return "not_found_in_collected_plans"
    return "offering_unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-catalog", type=Path, required=True)
    parser.add_argument("--recovery-catalog", type=Path, required=True)
    parser.add_argument("--base-coverage", type=Path, required=True)
    parser.add_argument("--recovery-coverage", type=Path, required=True)
    parser.add_argument("--base-summary", type=Path, required=True)
    parser.add_argument("--recovery-summary", type=Path, required=True)
    parser.add_argument("--base-validation", type=Path, required=True)
    parser.add_argument("--recovery-validation", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    parser.add_argument("--coverage-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--validation-output", type=Path, required=True)
    args = parser.parse_args()

    base_validation = load_json(args.base_validation)
    recovery_validation = load_json(args.recovery_validation)
    if base_validation.get("passed") is not True or recovery_validation.get("passed") is not True:
        raise SystemExit("both source validations must pass before merge")

    args.catalog_output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, catalog_name = tempfile.mkstemp(
        prefix=args.catalog_output.stem + "_", suffix=".partial", dir=args.catalog_output.parent
    )
    os.close(descriptor)
    catalog_temp = Path(catalog_name)
    case_ids: set[str] = set()
    source_labels: collections.Counter[str] = collections.Counter()
    catalog_schools: set[str] = set()
    with catalog_temp.open("w", encoding="utf-8", newline="\n") as output:
        for label, path in (
            ("base", args.base_catalog),
            ("recovery", args.recovery_catalog),
        ):
            for row in read_catalog(path):
                case_id = catalog_identity(row)
                if case_id in case_ids:
                    raise SystemExit(f"duplicate merged case id: {case_id}")
                case_ids.add(case_id)
                source_labels[label] += 1
                source = row.get("source")
                if isinstance(source, dict):
                    school_code = str(source.get("school_code") or "").strip()
                    if school_code:
                        catalog_schools.add(school_code)
                output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    fields, base_coverage = load_coverage(args.base_coverage)
    recovery_fields, recovery_coverage = load_coverage(args.recovery_coverage)
    if fields != recovery_fields or set(base_coverage) != set(recovery_coverage):
        raise SystemExit("coverage schemas or school-subject keys differ")
    status_counts: collections.Counter[str] = collections.Counter()
    subject_counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    descriptor, coverage_name = tempfile.mkstemp(
        prefix=args.coverage_output.stem + "_", suffix=".partial", dir=args.coverage_output.parent
    )
    os.close(descriptor)
    coverage_temp = Path(coverage_name)
    with coverage_temp.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for key in sorted(base_coverage):
            row = dict(base_coverage[key])
            recovery = recovery_coverage[key]
            for field in COUNT_FIELDS:
                row[field] = str(integer(row, field) + integer(recovery, field))
            status = merged_status(row)
            row["coverage_status"] = status
            writer.writerow(row)
            status_counts[status] += 1
            subject_counts[(key[1], key[2])][status] += 1

    base_summary = load_json(args.base_summary)
    recovery_summary = load_json(args.recovery_summary)
    by_subject = {
        f"{curriculum}:{subject}": {
            status: subject_counts[(curriculum, subject)].get(status, 0)
            for status in STATUS_ORDER
        }
        for curriculum, subject in sorted(subject_counts)
    }
    summary = {
        "unit_of_analysis": base_summary.get("unit_of_analysis"),
        "school_roster_rows": int(base_summary.get("school_roster_rows") or 0),
        "source_index_rows": int(base_summary.get("source_index_rows") or 0)
        + int(recovery_summary.get("source_index_rows") or 0),
        "catalog_rows": len(case_ids),
        "catalog_schools": len(catalog_schools),
        "coverage_rows": len(base_coverage),
        "coverage_status_counts": dict(status_counts),
        "by_subject": by_subject,
        "warning": "not_found_in_collected_plans does not mean the school did not offer the course",
        "recovery_merge": dict(source_labels),
    }
    validation = {
        "passed": True,
        "checks": {
            "base_validation_passed": True,
            "recovery_validation_passed": True,
            "case_ids_unique": len(case_ids) == sum(source_labels.values()),
            "coverage_keys_reconciled": len(base_coverage) == len(recovery_coverage),
        },
        "counts": {
            "strict_rows": len(case_ids),
            "catalog_rows": len(case_ids),
            "coverage_rows": len(base_coverage),
            "base_catalog_rows": source_labels["base"],
            "recovery_catalog_rows": source_labels["recovery"],
        },
        "provenance": {
            "base_validation": str(args.base_validation.resolve()),
            "recovery_validation": str(args.recovery_validation.resolve()),
        },
    }

    for path, value in (
        (args.summary_output, summary),
        (args.validation_output, validation),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".partial")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    os.replace(catalog_temp, args.catalog_output)
    os.replace(coverage_temp, args.coverage_output)

    report = {
        "catalog_rows": len(case_ids),
        "catalog_schools": len(catalog_schools),
        "coverage_rows": len(base_coverage),
        "coverage_status_counts": dict(status_counts),
        "catalog_sha256": sha256(args.catalog_output),
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
