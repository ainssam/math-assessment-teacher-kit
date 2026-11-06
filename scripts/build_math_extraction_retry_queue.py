"""Create a de-duplicated retry queue for incomplete math-plan extraction rows."""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import tempfile
from pathlib import Path


STATUS_RANK = {"ok": 4, "short": 3, "failed": 2, "missing": 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--input-glob", action="append", default=[])
    args = parser.parse_args()

    patterns = args.input_glob or [
        "math_subject_candidate_text_[0-9]*.jsonl",
        "math_allplan_remaining_text_[0-9]*.jsonl",
    ]
    inputs: list[Path] = []
    for pattern in patterns:
        inputs.extend(Path(value) for value in sorted(glob.glob(str(args.derived_dir / pattern))))
    if not inputs:
        raise SystemExit("no extraction batches found")
    for target in (args.output, args.summary_output):
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing output: {target}")

    best: dict[str, dict[str, object]] = {}
    status = collections.Counter()
    total = bad = duplicates = 0
    files: list[dict[str, object]] = []
    for path in inputs:
        file_rows = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                total += 1
                file_rows += 1
                source = record.get("source") or {}
                key = str(source.get("saved_path") or source.get("final_url") or "")
                value = str(record.get("extract_status") or "unknown")
                status[value] += 1
                current = best.get(key)
                if current is not None:
                    duplicates += 1
                if key and (
                    current is None
                    or (STATUS_RANK.get(value, 0), int(record.get("char_count") or 0))
                    > (STATUS_RANK.get(str(current.get("extract_status") or ""), 0), int(current.get("char_count") or 0))
                ):
                    best[key] = record
        files.append({"name": path.name, "rows": file_rows})

    retry_rows = [
        {"source": record.get("source") or {}, "final_status": record.get("extract_status")}
        for record in best.values()
        if str(record.get("extract_status") or "") != "ok"
    ]
    retry_rows.sort(key=lambda row: (
        str((row.get("source") or {}).get("school_code") or ""),
        str((row.get("source") or {}).get("candidate_name") or ""),
    ))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in retry_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temp_path, args.output)

    summary = {
        "input_files": files,
        "input_rows": total,
        "bad_json_rows": bad,
        "duplicate_source_rows": duplicates,
        "unique_sources": len(best),
        "input_status": dict(status),
        "retry_rows": len(retry_rows),
        "retry_reason": dict(collections.Counter(str(row.get("final_status") or "unknown") for row in retry_rows)),
    }
    fd, temp_name = tempfile.mkstemp(prefix=args.summary_output.stem + "_", suffix=".partial", dir=args.summary_output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, args.summary_output)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
