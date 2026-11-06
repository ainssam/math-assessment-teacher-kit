"""Audit automatically detected public task titles and write a compact report."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

METHOD_RE = re.compile(
    r"서술.?논술|구술.?발표|토의.?토론|실험.?실습|포트폴리오|프로젝트|"
    r"교사 관찰|자기평가|동료평가"
)
RUBRIC_RE = re.compile(r"(?:완성도|정확성|충실성|적절성|표현력|참여도|태도)$")
OBJECTIVE_RE = re.compile(r"(?:하는 능력|할 수 있다|하도록 한다|지키지 않음|보이지 않음)[.!]?$")
STANDARD_CODE_RE = re.compile(r"\[(?:10|12)[가-힣A-Za-z][^\]]+\]")
FOREIGN_RE = re.compile(r"영어|영문|저널|English|Lesson", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_title_audit.json",
    )
    return parser.parse_args()


def flags_for(title: str, subject: str) -> list[str]:
    flags: list[str] = []
    if not title.strip():
        flags.append("empty")
    has_checkbox = any(marker in title for marker in ("□", "◻", "☐", "☑", "■"))
    if has_checkbox or len(METHOD_RE.findall(title)) >= 2:
        flags.append("assessment_method_row")
    if title == "구체적 과제명 미탐지" or title == f"{subject} 수행평가":
        flags.append("generic_fallback")
    if RUBRIC_RE.search(title):
        flags.append("rubric_dimension")
    if OBJECTIVE_RE.search(title):
        flags.append("objective_sentence")
    if STANDARD_CODE_RE.search(title):
        flags.append("achievement_standard_as_title")
    if FOREIGN_RE.search(title):
        flags.append("possible_cross_subject_context")
    return flags


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT case_id, curriculum, subject, primary_task_name FROM cases ORDER BY case_id"
    )
    counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    total = 0
    for case_id, curriculum, subject, title in rows:
        total += 1
        for flag in flags_for(str(title), str(subject)):
            counts[flag] += 1
            if len(samples[flag]) < 8:
                samples[flag].append(
                    {
                        "case_id": str(case_id),
                        "curriculum": str(curriculum),
                        "subject": str(subject),
                        "title": str(title),
                    }
                )
    connection.close()
    hard_failures = counts["empty"] + counts["assessment_method_row"]
    result = {
        "passed": hard_failures == 0,
        "cases": total,
        "hard_failure_count": hard_failures,
        "flag_counts": dict(sorted(counts.items())),
        "samples": dict(sorted(samples.items())),
        "interpretation": (
            "Flags beyond hard failures are review queues, not proof that a title is wrong. "
            "Task titles are deterministic candidates extracted from public plan evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
