"""Merge a validated recovery catalogue into the base derived catalogue.

The two inputs remain untouched.  Coverage combines validated cell states so
that a newly found subject can replace an unknown without treating a successful
conversion from an incomplete school collection as comprehensive coverage.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_math_assessment_publish_db import case_identifier


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


def merged_status(base: str, recovery: str, *, evidence_only: bool) -> str:
    if base not in STATUS_ORDER or recovery not in STATUS_ORDER:
        raise SystemExit(f"unexpected coverage statuses: {base}, {recovery}")
    if evidence_only and recovery == "not_found_in_collected_plans":
        return base
    return min((base, recovery), key=STATUS_ORDER.index)


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
    parser.add_argument("--allow-coverage-union", action="store_true",
                        help="include schools present in only one separately validated period")
    parser.add_argument("--recovery-evidence-only", action="store_true",
                        help="preserve unknown cells when a targeted supplement finds no evidence")
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
    base_keys = set(base_coverage)
    recovery_keys = set(recovery_coverage)
    if fields != recovery_fields or (base_keys != recovery_keys and not args.allow_coverage_union):
        raise SystemExit("coverage schemas or school-subject keys differ")
    coverage_keys = base_keys | recovery_keys
    base_subjects = {key[1:] for key in base_keys}
    if args.allow_coverage_union and (
        {key[1:] for key in recovery_keys} != base_subjects
        or any(len(keys) != len({key[0] for key in keys}) * len(base_subjects)
               for keys in (base_keys, recovery_keys))
    ):
        raise SystemExit("each period must cover the complete shared subject grid")
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
        for key in sorted(coverage_keys):
            base = base_coverage.get(key)
            recovery = recovery_coverage.get(key)
            row = dict(base if base is not None else recovery)
            for field in COUNT_FIELDS:
                row[field] = str(integer(base or {}, field) + integer(recovery or {}, field))
            status = merged_status(base["coverage_status"], recovery["coverage_status"],
                                   evidence_only=args.recovery_evidence_only) if base and recovery else row["coverage_status"]
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
        "school_roster_rows": len({key[0] for key in coverage_keys}),
        "source_index_rows": int(base_summary.get("source_index_rows") or 0)
        + int(recovery_summary.get("source_index_rows") or 0),
        "catalog_rows": len(case_ids),
        "catalog_schools": len(catalog_schools),
        "coverage_rows": len(coverage_keys),
        "coverage_status_counts": dict(status_counts),
        "by_subject": by_subject,
        "warning": "not_found_in_collected_plans does not mean the school did not offer the course",
        "recovery_merge": dict(source_labels),
    }
    if args.allow_coverage_union:
        summary["period_coverage_rows"] = {
            "base": len(base_keys), "recovery": len(recovery_keys), "both": len(base_keys & recovery_keys),
        }
    validation = {
        "passed": True,
        "checks": {
            "base_validation_passed": True,
            "recovery_validation_passed": True,
            "case_ids_unique": len(case_ids) == sum(source_labels.values()),
            "coverage_keys_reconciled": len(coverage_keys) == sum(status_counts.values()),
        },
        "counts": {
            "strict_rows": len(case_ids),
            "catalog_rows": len(case_ids),
            "coverage_rows": len(coverage_keys),
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
        "coverage_rows": len(coverage_keys),
        "coverage_status_counts": dict(status_counts),
        "catalog_sha256": sha256(args.catalog_output),
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
