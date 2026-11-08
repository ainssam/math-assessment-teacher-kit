"""Build a nationwide school-by-math-subject assessment catalog and coverage matrix.

The catalog grain is one extracted source document x detected math subject.  The
coverage matrix is one school x curriculum x subject and deliberately separates
"not found in the collected plans" from extraction failure and offering
uncertainty.  Absence from the corpus is never treated as proof that a school
does not offer the course.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

SUBJECTS: dict[str, tuple[str, ...]] = {
    "2015": (
        "수학",
        "수학Ⅰ",
        "수학Ⅱ",
        "미적분",
        "확률과 통계",
        "기하",
        "실용 수학",
        "경제 수학",
        "수학과제 탐구",
        "인공지능 수학",
    ),
    "2022": (
        "공통수학1",
        "공통수학2",
        "기본수학1",
        "기본수학2",
        "대수",
        "미적분Ⅰ",
        "미적분Ⅱ",
        "확률과 통계",
        "기하",
        "경제 수학",
        "인공지능 수학",
        "직무 수학",
        "수학과 문화",
        "실용 통계",
        "수학과제 탐구",
    ),
}
SHARED_SUBJECTS = set(SUBJECTS["2015"]) & set(SUBJECTS["2022"])


def atomic_text_path(target: Path) -> tuple[Path, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".partial", dir=target.parent)
    return Path(name), fd


def source_key(source: dict[str, object]) -> str:
    return str(
        source.get("saved_path") or source.get("final_url") or source.get("candidate_name") or ""
    )


def school_key(source: dict[str, object]) -> str:
    return str(source.get("school_code") or source.get("school_name") or "")


def extract_years(text: str) -> list[int]:
    return sorted({int(value) for value in re.findall(r"(?<!\d)(20(?:2[2-9]|3\d))\s*학년도", text)})


def extract_grades(text: str) -> list[int]:
    values = {int(value) for value in re.findall(r"(?<!\d)([123])\s*학년", text)}
    values.update(int(value) for value in re.findall(r"(?:고등학교|고)\s*([123])(?!\d)", text))
    return sorted(values)


def extract_semesters(text: str) -> list[int]:
    return sorted({int(value) for value in re.findall(r"(?<!\d)([12])\s*학기", text)})


def confirmed_cover_grade(source: dict[str, object], text: str) -> int | None:
    """Use an explicit cover heading when identical PDFs carry different names."""
    if (
        source.get("confirmed_semester") not in (1, 2)
        or Path(source_key(source)).suffix.lower() != ".pdf"
    ):
        return None
    heading = re.search(r"(?m)^\s*20\d{2}\s*학년도\s*([123])\s*학년\s*([12])\s*학기", text[:400])
    if heading and int(heading[2]) == source["confirmed_semester"]:
        return int(heading[1])
    return None


def transition_curriculum(year: int, grade: int | None) -> str | None:
    if year <= 2024:
        return "2015"
    if year >= 2027:
        return "2022"
    if grade is None:
        return None
    if year == 2025:
        return "2022" if grade == 1 else "2015"
    if year == 2026:
        return "2022" if grade in {1, 2} else "2015"
    return None


def resolve_curriculum(
    record: dict[str, object], years: list[int], grades: list[int]
) -> tuple[str, str]:
    subject = str(record.get("subject") or "")
    hint = str(record.get("curriculum_hint") or "")
    if subject == "인공지능 수학":
        # Old detector records labelled this alias 2022-only. Its name and code
        # family also occur in the 2015 course added by notice 2020-236, so that
        # inherited hint cannot override the explicit cohort or resolve a mix.
        hint = ""
    allowed = [curriculum for curriculum, names in SUBJECTS.items() if subject in names]
    if len(allowed) == 1:
        return allowed[0], "subject_unique_to_curriculum"
    if hint in {"2015", "2022"} and hint in allowed:
        return hint, "detector_curriculum_hint"
    inferred: set[str] = set()
    if len(years) == 1:
        if grades:
            for grade in grades:
                value = transition_curriculum(years[0], grade)
                if value:
                    inferred.add(value)
        else:
            value = transition_curriculum(years[0], None)
            if value:
                inferred.add(value)
    if len(inferred) == 1:
        return next(iter(inferred)), "transition_year_and_grade"
    return "shared", "curriculum_unresolved"


def read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"malformed JSONL {path}:{line_no}: {exc}") from exc
            if isinstance(value, dict):
                yield value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schools", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--strict-input", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    parser.add_argument("--coverage-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument(
        "--incomplete-schools",
        type=Path,
        help="JSON list of school keys with unresolved source coverage",
    )
    args = parser.parse_args()
    incomplete_schools = (
        set(json.loads(args.incomplete_schools.read_text(encoding="utf-8")))
        if args.incomplete_schools
        else set()
    )

    for output in (args.catalog_output, args.coverage_output, args.summary_output):
        if output.exists():
            raise SystemExit(f"refusing to overwrite existing output: {output}")

    schools: dict[str, dict[str, str]] = {}
    with args.schools.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = str(row.get("school_code") or row.get("school_name") or "")
            if key and key not in schools:
                schools[key] = row

    source_status: dict[str, str] = {}
    school_source_status: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    sources_with_cover_grade: dict[tuple[str, str], list[tuple[int, dict[str, object]]]] = (
        collections.defaultdict(list)
    )
    for record in read_jsonl(args.source_index):
        source = record.get("source") or {}
        if not isinstance(source, dict):
            continue
        key = source_key(source)
        status = str(record.get("extract_status") or "unknown")
        if key:
            source_status[key] = status
        school = school_key(source)
        if school:
            school_source_status[school][status] += 1
            grade = confirmed_cover_grade(source, str(record.get("text") or ""))
            digest = str(record.get("sha256") or "")
            if grade and digest:
                sources_with_cover_grade[(school, digest)].append((grade, source))

    preferred_sources = {}
    for identity, options in sources_with_cover_grade.items():
        cover_grades = {grade for grade, _ in options}
        declared_grades = {
            tuple(extract_grades(str(source.get("candidate_name") or ""))) for _, source in options
        }
        if len(cover_grades) != 1 or len(declared_grades) <= 1:
            continue
        grade = next(iter(cover_grades))
        preferred = next(
            (
                source
                for _, source in options
                if extract_grades(str(source.get("candidate_name") or "")) == [grade]
            ),
            None,
        )
        if preferred:
            preferred_sources[identity] = preferred

    explicit_sources: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            subject = str(row.get("subject_canonical") or "")
            school = str(row.get("school_code") or row.get("school_name") or "")
            if school and subject not in {"", "unknown", "수학"}:
                explicit_sources[(school, subject)].append(source_key(row))

    catalog_rows: list[dict[str, object]] = []
    found: dict[tuple[str, str, str], list[dict[str, object]]] = collections.defaultdict(list)
    ambiguous_found: dict[tuple[str, str], list[dict[str, object]]] = collections.defaultdict(list)
    for record in read_jsonl(args.strict_input):
        source = record.get("source") or {}
        if not isinstance(source, dict):
            continue
        original_source = source
        preferred = preferred_sources.get((school_key(source), str(record.get("sha256") or "")))
        if preferred and extract_grades(str(source.get("candidate_name") or "")) != extract_grades(
            str(preferred.get("candidate_name") or "")
        ):
            source = preferred
        name = str(source.get("candidate_name") or "")
        evidence = str(record.get("evidence_text") or "")
        years = extract_years(name) or extract_years(evidence[:3000])
        grades = extract_grades(name)
        confirmed_semester = source.get("confirmed_semester")
        semesters = (
            [confirmed_semester] if confirmed_semester in (1, 2) else extract_semesters(name)
        )
        curriculum, basis = resolve_curriculum(record, years, grades)
        enriched = dict(record)
        if source is not original_source and source_key(source) != source_key(original_source):
            enriched["source"] = source
            enriched["duplicate_attachment_grade_reconciled_from"] = source_key(original_source)
        enriched.update(
            {
                "resolved_curriculum": curriculum,
                "curriculum_resolution_basis": basis,
                "academic_years": years,
                "grades": grades,
                "semesters": semesters,
            }
        )
        catalog_rows.append(enriched)
        school = school_key(source)
        subject = str(record.get("subject") or "")
        if curriculum in {"2015", "2022"}:
            found[(school, curriculum, subject)].append(enriched)
        elif curriculum == "shared":
            ambiguous_found[(school, subject)].append(enriched)

    catalog_rows.sort(
        key=lambda row: (
            str((row.get("source") or {}).get("school_code") or ""),
            str(row.get("resolved_curriculum") or ""),
            str(row.get("subject") or ""),
            str((row.get("source") or {}).get("candidate_name") or ""),
        )
    )

    catalog_temp, fd = atomic_text_path(args.catalog_output)
    os.close(fd)
    with catalog_temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in catalog_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    coverage_fields = [
        "school_code",
        "school_name",
        "region",
        "district",
        "school_type",
        "curriculum",
        "subject",
        "coverage_status",
        "found_documents",
        "ambiguous_curriculum_documents",
        "explicit_subject_documents",
        "explicit_subject_incomplete",
        "school_extracted_ok",
        "school_extracted_short",
        "school_extracted_failed",
        "interpretation_note",
    ]
    coverage_temp, fd = atomic_text_path(args.coverage_output)
    os.close(fd)
    status_counts: collections.Counter[str] = collections.Counter()
    subject_counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    with coverage_temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=coverage_fields)
        writer.writeheader()
        for school, metadata in sorted(
            schools.items(),
            key=lambda item: (
                item[1].get("region_sido", ""),
                item[1].get("school_name", ""),
                item[0],
            ),
        ):
            school_status = school_source_status.get(school, collections.Counter())
            for curriculum, subjects in SUBJECTS.items():
                for subject in subjects:
                    direct = found.get((school, curriculum, subject), [])
                    ambiguous = (
                        ambiguous_found.get((school, subject), [])
                        if subject in SHARED_SUBJECTS
                        else []
                    )
                    explicit = explicit_sources.get((school, subject), [])
                    incomplete = sum(
                        source_status.get(key, "missing")
                        in {"failed", "short", "missing", "unknown"}
                        for key in explicit
                    )
                    if direct:
                        status = "found"
                    elif ambiguous:
                        status = "found_curriculum_ambiguous"
                    elif incomplete:
                        status = "extraction_failed"
                    elif school not in incomplete_schools and school_status.get("ok", 0):
                        status = "not_found_in_collected_plans"
                    else:
                        status = "offering_unknown"
                    status_counts[status] += 1
                    subject_counts[(curriculum, subject)][status] += 1
                    writer.writerow(
                        {
                            "school_code": school,
                            "school_name": metadata.get("school_name", ""),
                            "region": metadata.get("region_sido") or metadata.get("region", ""),
                            "district": metadata.get("region_sgg") or metadata.get("district", ""),
                            "school_type": metadata.get("high_school_type")
                            or metadata.get("school_type", ""),
                            "curriculum": curriculum,
                            "subject": subject,
                            "coverage_status": status,
                            "found_documents": len(direct),
                            "ambiguous_curriculum_documents": len(ambiguous),
                            "explicit_subject_documents": len(explicit),
                            "explicit_subject_incomplete": incomplete,
                            "school_extracted_ok": school_status.get("ok", 0),
                            "school_extracted_short": school_status.get("short", 0),
                            "school_extracted_failed": school_status.get("failed", 0),
                            "interpretation_note": (
                                "absence is not proof that the course was not offered"
                            ),
                        }
                    )

    by_subject: dict[str, object] = {}
    for curriculum, subjects in SUBJECTS.items():
        for subject in subjects:
            counter = subject_counts[(curriculum, subject)]
            key = f"{curriculum}:{subject}"
            by_subject[key] = {
                status: counter.get(status, 0)
                for status in (
                    "found",
                    "found_curriculum_ambiguous",
                    "extraction_failed",
                    "not_found_in_collected_plans",
                    "offering_unknown",
                )
            }
    catalog_school_count = len(
        {
            school_key(row.get("source") or {})
            for row in catalog_rows
            if school_key(row.get("source") or {})
        }
    )
    summary = {
        "unit_of_analysis": {
            "catalog": "one source document x detected math subject",
            "coverage": "one school x curriculum x math subject",
        },
        "school_roster_rows": len(schools),
        "source_index_rows": sum(
            school_source_status[school].total() for school in school_source_status
        ),
        "catalog_rows": len(catalog_rows),
        "catalog_schools": catalog_school_count,
        "coverage_rows": len(schools) * sum(len(values) for values in SUBJECTS.values()),
        "coverage_status_counts": dict(status_counts),
        "by_subject": by_subject,
        "warning": "not_found_in_collected_plans does not mean the school did not offer the course",
    }
    summary_temp, fd = atomic_text_path(args.summary_output)
    os.close(fd)
    with summary_temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    os.replace(catalog_temp, args.catalog_output)
    os.replace(coverage_temp, args.coverage_output)
    os.replace(summary_temp, args.summary_output)
    print(
        json.dumps(
            {
                "schools": len(schools),
                "source_rows": summary["source_index_rows"],
                "catalog_rows": len(catalog_rows),
                "catalog_schools": catalog_school_count,
                "coverage_rows": summary["coverage_rows"],
                "coverage_status": dict(status_counts),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
