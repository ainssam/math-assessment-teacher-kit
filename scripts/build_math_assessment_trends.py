"""Aggregate deterministic nationwide trends from the strict assessment catalog."""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import statistics
import tempfile
from pathlib import Path

from build_school_subject_assessment_catalog import SHARED_SUBJECTS, SUBJECTS


def atomic_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".partial", dir=target.parent)
    os.close(fd)
    return Path(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, action="append", required=True, help="catalog JSONL; repeatable")
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    for target in (args.csv_output, args.json_output):
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing output: {target}")

    groups: dict[tuple[str, str], list[dict[str, object]]] = collections.defaultdict(list)
    bad = 0
    for catalog_path in args.catalog:
        with catalog_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                groups[(str(row.get("resolved_curriculum") or "shared"), str(row.get("subject") or ""))].append(row)

    expected_groups = [(curriculum, subject) for curriculum, subjects in SUBJECTS.items() for subject in subjects]
    expected_groups += [("shared", subject) for subject in sorted(SHARED_SUBJECTS)]
    fieldnames = [
        "curriculum", "subject", "documents", "schools", "academic_years",
        "grade1_documents", "grade2_documents", "grade3_documents",
        "rubric_documents", "achievement_standard_documents", "weight_or_points_documents",
        "assessment_method_documents", "median_review_score", "action_tag_document_counts",
        "action_tag_school_counts", "task_name_candidates", "top_task_name_candidates",
    ]
    csv_temp = atomic_path(args.csv_output)
    detailed: dict[str, object] = {}
    with csv_temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for curriculum, subject in expected_groups:
            rows = groups.get((curriculum, subject), [])
            schools = {
                str((row.get("source") or {}).get("school_code") or (row.get("source") or {}).get("school_name") or "")
                for row in rows
            } - {""}
            years = sorted({int(year) for row in rows for year in (row.get("academic_years") or [])})
            grade_counts = collections.Counter(int(grade) for row in rows for grade in (row.get("grades") or []))
            marker_docs = collections.Counter()
            action_docs = collections.Counter()
            action_schools: dict[str, set[str]] = collections.defaultdict(set)
            task_names: collections.Counter[str] = collections.Counter()
            scores: list[int] = []
            for row in rows:
                markers = row.get("marker_counts") or {}
                for marker in ("rubric", "achievement_standard", "weight_or_points", "assessment_method"):
                    if int(markers.get(marker) or 0) > 0:
                        marker_docs[marker] += 1
                school = str((row.get("source") or {}).get("school_code") or (row.get("source") or {}).get("school_name") or "")
                for action in set(str(value) for value in (row.get("action_tags") or [])):
                    action_docs[action] += 1
                    if school:
                        action_schools[action].add(school)
                task_names.update(str(value) for value in (row.get("task_name_candidates") or []) if str(value).strip())
                scores.append(int(row.get("review_score") or row.get("evidence_score") or 0))
            action_doc_counts = dict(sorted(action_docs.items(), key=lambda item: (-item[1], item[0])))
            action_school_counts = {name: len(values) for name, values in sorted(action_schools.items(), key=lambda item: (-len(item[1]), item[0]))}
            record = {
                "curriculum": curriculum,
                "subject": subject,
                "documents": len(rows),
                "schools": len(schools),
                "academic_years": ",".join(map(str, years)),
                "grade1_documents": grade_counts.get(1, 0),
                "grade2_documents": grade_counts.get(2, 0),
                "grade3_documents": grade_counts.get(3, 0),
                "rubric_documents": marker_docs.get("rubric", 0),
                "achievement_standard_documents": marker_docs.get("achievement_standard", 0),
                "weight_or_points_documents": marker_docs.get("weight_or_points", 0),
                "assessment_method_documents": marker_docs.get("assessment_method", 0),
                "median_review_score": statistics.median(scores) if scores else "",
                "action_tag_document_counts": json.dumps(action_doc_counts, ensure_ascii=False, separators=(",", ":")),
                "action_tag_school_counts": json.dumps(action_school_counts, ensure_ascii=False, separators=(",", ":")),
                "task_name_candidates": sum(task_names.values()),
                "top_task_name_candidates": json.dumps(task_names.most_common(20), ensure_ascii=False, separators=(",", ":")),
            }
            writer.writerow(record)
            detailed[f"{curriculum}:{subject}"] = {
                **record,
                "academic_years": years,
                "action_tag_document_counts": action_doc_counts,
                "action_tag_school_counts": action_school_counts,
                "top_task_name_candidates": task_names.most_common(20),
            }

    all_rows = [row for rows in groups.values() for row in rows]
    all_schools = {
        str((row.get("source") or {}).get("school_code") or (row.get("source") or {}).get("school_name") or "")
        for row in all_rows
    } - {""}
    summary = {
        "unit_of_analysis": "strict source document x math subject",
        "input_catalogs": [str(path) for path in args.catalog],
        "catalog_rows": len(all_rows),
        "catalog_schools": len(all_schools),
        "bad_json_rows": bad,
        "subject_groups": detailed,
        "caution": "action tags are deterministic text signals near performance-assessment context, not model-reviewed task labels",
    }
    json_temp = atomic_path(args.json_output)
    with json_temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(csv_temp, args.csv_output)
    os.replace(json_temp, args.json_output)
    print(json.dumps({"catalog_rows": len(all_rows), "catalog_schools": len(all_schools), "groups": len(detailed), "bad_json_rows": bad}, ensure_ascii=False))


if __name__ == "__main__":
    main()
