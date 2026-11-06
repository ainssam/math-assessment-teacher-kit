"""Inspect subject-local evidence without printing source paths or full documents."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("data/derived/math_assessment_school_subject_catalog_v2.jsonl"),
    )
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--context", type=int, default=6)
    parser.add_argument("--start-line", type=int, default=0)
    parser.add_argument("--line-count", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.catalog.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if str(row.get("sha256") or "") != args.sha256:
                continue
            if args.subject not in str(row.get("subject") or ""):
                continue
            evidence = str(row.get("evidence_text") or "")
            lines = evidence.splitlines()
            if args.start_line:
                start = max(0, args.start_line - 1)
                end = min(len(lines), start + args.line_count)
                for line_number in range(start, end):
                    print(f"{line_number + 1:05d} {lines[line_number][:500]}")
                return
            subject_pattern = re.compile(r"미\s*적\s*분", re.IGNORECASE)
            hits = [index for index, value in enumerate(lines) if subject_pattern.search(value)]
            for hit_number, index in enumerate(hits[:12], 1):
                start = max(0, index - args.context)
                end = min(len(lines), index + args.context + 1)
                print(f"--- subject hit {hit_number}/{len(hits)} at line {index + 1} ---")
                for line_number in range(start, end):
                    marker = ">" if line_number == index else " "
                    print(f"{marker}{line_number + 1:05d} {lines[line_number][:240]}")
            return
    raise SystemExit("source sha256 not found")


if __name__ == "__main__":
    main()
