"""Build the full-text queue omitted by the first-pass subject detector."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from pathlib import Path


GENERIC_NAME = re.compile(r"교수|평가.?계획|전과목|교과별|학년별")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extracted-index", type=Path, help="optional previously extracted source index")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    extracted_paths: set[str] = set()
    if args.extracted_index:
        with args.extracted_index.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                source = record.get("source") or {}
                saved_path = str(source.get("saved_path") or "")
                if saved_path:
                    extracted_paths.add(saved_path)

    candidates: list[dict[str, str]] = []
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("subject_canonical") in {"unknown", "수학"}:
                if not GENERIC_NAME.search(row.get("candidate_name", "")):
                    continue
            candidates.append(row)
    candidates.sort(key=lambda row: (row["subject_canonical"], row["school_name"], row["candidate_name"]))
    remaining = [row for row in candidates if row.get("saved_path", "") not in extracted_paths]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as output:
        for source in remaining:
            output.write(json.dumps({"source": source}, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temp_path, args.output)
    schools = {row.get("school_code") or row.get("school_name") for row in remaining}
    print(json.dumps({"candidate_total": len(candidates), "already_extracted": len(extracted_paths), "remaining": len(remaining), "remaining_schools": len([school for school in schools if school])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
