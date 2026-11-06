"""Build a deterministic manifest of SCHOOLINFO 4-가 files likely to contain math plans.

This step deliberately does not read or interpret document contents.  It only records
provenance, applies conservative filename aliases, and marks generic files for later
text scanning.  Semantic extraction is a separate, model-gated step.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from pathlib import Path


ALIASES: list[tuple[str, str, str]] = [
    ("미적분Ⅱ", "미적분Ⅱ", r"미적분\s*(?:[Ⅱ2]|II(?!I))"),
    ("미적분Ⅰ", "미적분Ⅰ", r"미적분\s*(?:[Ⅰ1]|I(?!I))"),
    ("미적분", "미적분", r"미적분(?!\s*[ⅠⅡI12])"),
    ("확률과 통계", "확률과 통계", r"확률\s*(?:과|[·ㆍ.])?\s*통계"),
    ("수학과제탐구", "수학과제 탐구", r"수학\s*과제\s*탐구"),
    ("인공지능 수학", "인공지능 수학", r"인공지능\s*수학"),
    ("경제 수학", "경제 수학", r"경제\s*수학"),
    ("실용 통계", "실용 통계", r"실용\s*통계"),
    ("공통수학2", "공통수학2", r"공통\s*수학\s*(?:[Ⅱ2]|II(?!I))"),
    ("공통수학1", "공통수학1", r"공통\s*수학\s*(?:[Ⅰ1]|I(?!I))"),
    ("기본수학2", "기본수학2", r"기본\s*수학\s*(?:[Ⅱ2]|II(?!I))"),
    ("기본수학1", "기본수학1", r"기본\s*수학\s*(?:[Ⅰ1]|I(?!I))"),
    ("수학Ⅱ", "수학Ⅱ", r"수학\s*(?:[Ⅱ2]|II(?!I))"),
    ("수학Ⅰ", "수학Ⅰ", r"수학\s*(?:[Ⅰ1]|I(?!I))"),
    ("수학과 문화", "수학과 문화", r"수학\s*과\s*문화"),
    ("실용 수학", "실용 수학", r"실용\s*수학"),
    ("직무 수학", "직무 수학", r"직무\s*수학"),
    ("기하", "기하", r"기하"),
    ("대수", "대수", r"대수"),
    # ``교수학습`` is present in nearly every plan filename; exclude that
    # substring so the generic alias remains a candidate, not a false hit.
    ("수학", "수학", r"수학(?!습)"),
]


def classify(name: str) -> tuple[str, str, str]:
    for label, canonical, pattern in ALIASES:
        if re.search(pattern, name, flags=re.IGNORECASE):
            return label, canonical, "filename_alias"
    return "unknown", "unknown", "needs_text_scan"


def curriculum(year_text: str, name: str) -> str:
    # Prefer an explicit year in the filename.  Schoolinfo URLs can contain both
    # the current disclosure year and the attachment's actual JG_YEAR.
    name_years = [int(y) for y in re.findall(r"20\d{2}", name)]
    if name_years:
        years = name_years
    else:
        jg_years = [int(y) for y in re.findall(r"JG_YEAR(?:=|%3D)(20\d{2})", year_text, flags=re.IGNORECASE)]
        years = jg_years or [int(y) for y in re.findall(r"20\d{2}", year_text)]
    if any(y >= 2025 for y in years):
        return "2022_candidate"
    if any(2015 <= y <= 2024 for y in years):
        return "2015_candidate"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if args.log.suffix.lower() == ".jsonl":
        with args.log.open("r", encoding="utf-8") as handle:
            source_rows = [json.loads(line) for line in handle if line.strip()]
    else:
        with args.log.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
    for row in source_rows:
        if row.get("result") != "downloaded":
            continue
        if row.get("item_no") not in {None, "", "4-가"}:
            continue
        if row.get("record_type") not in {None, "", "attachment"}:
            continue
        path = row.get("saved_path", "")
        key = path or row.get("final_url", "")
        if key in seen:
            continue
        seen.add(key)
        name = row.get("candidate_name", "")
        raw, canonical, match_type = classify(name)
        cur = curriculum(
            " ".join(
                (
                    str(row.get("year", "")),
                    row.get("final_url", ""),
                    row.get("source_url", ""),
                )
            ),
            name,
        )
        rows.append(
            {
                "curriculum_candidate": cur,
                "year": row.get("year", ""),
                "school_code": row.get("school_code", ""),
                "school_name": row.get("school_name", ""),
                "region": row.get("region", row.get("sido", "")),
                "candidate_name": name,
                "subject_match": raw,
                "subject_canonical": canonical,
                "match_type": match_type,
                "needs_text_scan": "false" if match_type == "filename_alias" else "true",
                "saved_path": _local_path(path),
                "source_saved_path": path,
                "source_url": row.get("source_url", ""),
                "final_url": row.get("final_url", ""),
                "size_bytes": row.get("size_bytes", ""),
            }
        )

    rows.sort(key=lambda r: (r["curriculum_candidate"], r["subject_canonical"], r["school_name"], r["candidate_name"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["curriculum_candidate"])
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, args.output)

    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['curriculum_candidate']}::{row['subject_canonical']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"rows={len(rows)} schools={len({r['school_code'] for r in rows})}")
    for key, value in sorted(counts.items()):
        print(f"{key}={value}")


def _local_path(source_path: str) -> str:
    marker = "교육과정운영계획/data/raw/4ga/"
    if marker in source_path:
        return "data/raw/schoolinfo/4ga/" + source_path.split(marker, 1)[1]
    return source_path


if __name__ == "__main__":
    main()
