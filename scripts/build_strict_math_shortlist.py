"""Validate subject evidence, deduplicate it, and build a diverse shortlist."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.math_subject_aliases import SUBJECT_PATTERNS, is_semester_course_plan_heading


CODE_KEYS = {
    "공통수학1": "공수1", "공통수학2": "공수2", "기본수학1": "기수1",
    "기본수학2": "기수2", "미적분Ⅰ": "미적Ⅰ", "미적분Ⅱ": "미적Ⅱ",
    "대수": "대수", "기하": "기하", "확률과 통계": "확통",
    "경제 수학": "경수", "실용 수학": "실수", "수학과제 탐구": "수과",
    "수학Ⅰ": "수학Ⅰ", "수학Ⅱ": "수학Ⅱ", "미적분": "미적분",
    "인공지능 수학": "인수", "직무 수학": "직수",
    "수학과 문화": "수문", "실용 통계": "실통",
}


def subject_pattern(subject: str) -> str | None:
    for _, name, pattern in SUBJECT_PATTERNS:
        if name == subject:
            return pattern.removeprefix("(?m)")
    return None


def evidence_strength(record: dict[str, object]) -> tuple[int, list[str]]:
    subject = str(record.get("subject") or "")
    pattern = subject_pattern(subject)
    if not pattern:
        return 0, []
    source = record.get("source") or {}
    text = str(record.get("evidence_text") or "")
    reasons: list[str] = []
    strength = 0
    if source.get("match_type") == "filename_alias" and source.get("subject_canonical") == subject:
        strength += 5
        reasons.append("filename_alias")
    code_key = CODE_KEYS.get(subject)
    if code_key and re.search(rf"\[(?:10|12){re.escape(code_key)}-?\d{{2}}-\d{{2}}\]", text):
        strength += 5
        reasons.append("achievement_code")
    label_patterns = (
        rf"(?:과목\s*명?|교과\s*목?)\s*[:：|]?\s*(?:<|\[)?\s*{pattern}\s*(?:>|\])?",
        rf"(?m)^\s*(?:#+\s*)?(?:<|\[)?\s*{pattern}\s*(?:>|\])?\s*$",
        rf"\|\s*(?:과목\s*명?|교과\s*목?)\s*\|\s*{pattern}\s*\|",
        rf"(?m)^\s*#+\s*\d{{4}}\s*학년도[^\n]{{0,180}}[<(\[]\s*{pattern}\s*[>)\]][^\n]{{0,120}}평가\s*계획[^\n]*$",
    )
    if any(re.search(label, text, flags=re.IGNORECASE) for label in label_patterns) or any(
        is_semester_course_plan_heading(line, pattern) for line in text.splitlines()
    ):
        strength += 4
        reasons.append("subject_label")
    if re.search(rf"(?:선택\s*과목|교과)\s*[:：]?\s*{pattern}", text, flags=re.IGNORECASE):
        strength += 2
        reasons.append("course_context")
    return strength, reasons


def key(record: dict[str, object]) -> tuple[str, str, str]:
    source = record.get("source") or {}
    source_key = str(record.get("sha256") or source.get("saved_path") or source.get("source_url") or "")
    return source_key, str(record.get("curriculum_hint") or ""), str(record.get("subject") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--strict-output", type=Path, required=True)
    parser.add_argument("--shortlist-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--per-subject", type=int, default=25)
    args = parser.parse_args()

    raw_rows = 0
    valid_rows: list[dict[str, object]] = []
    rejected = collections.Counter()
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw_rows += 1
            record = json.loads(line)
            strength, reasons = evidence_strength(record)
            markers = record.get("marker_counts") or {}
            if strength < 4:
                rejected["weak_subject_evidence"] += 1
                continue
            if int(markers.get("performance_assessment") or 0) == 0:
                rejected["no_performance_assessment_marker"] += 1
                continue
            enriched = dict(record)
            enriched["subject_evidence_strength"] = strength
            enriched["subject_evidence_reasons"] = reasons
            enriched["review_score"] = int(record.get("evidence_score") or 0) + strength * 3
            valid_rows.append(enriched)

    best: dict[tuple[str, str, str], dict[str, object]] = {}
    duplicates = 0
    for record in valid_rows:
        identity = key(record)
        current = best.get(identity)
        if current is None or int(record["review_score"]) > int(current["review_score"]):
            if current is not None:
                duplicates += 1
            best[identity] = record
        else:
            duplicates += 1
    strict_rows = sorted(best.values(), key=lambda row: (-int(row["review_score"]), str(row.get("subject")), str((row.get("source") or {}).get("school_name") or "")))

    grouped: dict[tuple[str, str], list[dict[str, object]]] = collections.defaultdict(list)
    for record in strict_rows:
        grouped[(str(record.get("curriculum_hint") or ""), str(record.get("subject") or ""))].append(record)
    shortlist: list[dict[str, object]] = []
    for group, records in sorted(grouped.items()):
        used_schools: set[str] = set()
        selected = 0
        for record in records:
            source = record.get("source") or {}
            school = str(source.get("school_code") or source.get("school_name") or "")
            if school and school in used_schools:
                continue
            shortlist.append(record)
            if school:
                used_schools.add(school)
            selected += 1
            if selected >= args.per_subject:
                break

    for target, rows in ((args.strict_output, strict_rows), (args.shortlist_output, shortlist)):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".partial", dir=target.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        with temp_path.open("w", encoding="utf-8", newline="\n") as output:
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temp_path, target)

    strict_counts = collections.Counter((str(row.get("curriculum_hint") or ""), str(row.get("subject") or "")) for row in strict_rows)
    shortlist_counts = collections.Counter((str(row.get("curriculum_hint") or ""), str(row.get("subject") or "")) for row in shortlist)
    summary = {
        "input_rows": raw_rows,
        "pre_dedup_valid_rows": len(valid_rows),
        "strict_unique_rows": len(strict_rows),
        "duplicate_rows_removed": duplicates,
        "rejected": dict(rejected),
        "shortlist_rows": len(shortlist),
        "per_subject_limit": args.per_subject,
        "strict_counts": {f"{curriculum}:{subject}": count for (curriculum, subject), count in sorted(strict_counts.items())},
        "shortlist_counts": {f"{curriculum}:{subject}": count for (curriculum, subject), count in sorted(shortlist_counts.items())},
        "score_note": "review_score is deterministic evidence completeness, not final quality judgment",
    }
    fd, temp_name = tempfile.mkstemp(prefix=args.summary_output.stem + "_", suffix=".partial", dir=args.summary_output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
        output.write("\n")
    os.replace(temp_path, args.summary_output)
    print(json.dumps({"strict_rows": len(strict_rows), "shortlist_rows": len(shortlist), "rejected": dict(rejected), "duplicates_removed": duplicates}, ensure_ascii=False))


if __name__ == "__main__":
    main()
