"""Retry only previously short/failed generic assessment records.

The full index is kept immutable. This script reads the merged index, retries
the derived text conversion for records whose first pass was ``short`` or
``failed``, and writes a separate provenance-preserving JSONL artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from extract_math_assessment_batch import extract
from math_subject_aliases import curriculum_from_codes, subject_hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--kordoc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    retry_rows: list[dict[str, object]] = []
    with args.input_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("extract_status") in {"short", "failed"}:
                retry_rows.append(record)

    def process(record: dict[str, object]) -> dict[str, object]:
        source = record.get("source") or {}
        saved_path = str(source.get("saved_path", ""))
        path = args.project_root / saved_path
        previous_status = record.get("extract_status")
        if not path.exists():
            text, status, digest = f"[missing: {path}]", "missing", ""
        else:
            text, status = extract(path, args.kordoc, args.project_root)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "source": source,
            "sha256": digest,
            "previous_status": previous_status,
            "extract_status": status,
            "char_count": len(text),
            "subject_hits": subject_hits(text),
            "curriculum_code_hints": curriculum_from_codes(text),
            "text": text,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for result in pool.map(process, retry_rows):
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"retry_total={len(retry_rows)} output={args.output}")


if __name__ == "__main__":
    main()
