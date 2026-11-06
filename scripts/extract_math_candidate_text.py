"""Extract full text for the content-confirmed math candidate index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from extract_math_assessment_batch import extract
from math_subject_aliases import curriculum_from_codes, subject_hits


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--kordoc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="detect subjects and extraction status without retaining full source text",
    )
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    with args.input_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    selected = rows[args.offset : args.offset + args.limit]

    def process(record: dict[str, object]) -> dict[str, object]:
        source = record.get("source") or {}
        path = args.project_root / str(source.get("saved_path", ""))
        if not path.exists():
            text, status, digest = f"[missing: {path}]", "missing", ""
        else:
            try:
                text, status = extract(path, args.kordoc, args.project_root)
                digest = file_sha256(path)
            except Exception as exc:  # keep the batch reconcilable after one bad source
                text, status, digest = f"[extract exception: {type(exc).__name__}: {exc}]", "failed", ""
        return {
            "source": source,
            "sha256": digest,
            "index_status": record.get("final_status"),
            "extract_status": status,
            "char_count": len(text),
            "subject_hits": subject_hits(text),
            "curriculum_code_hints": curriculum_from_codes(text),
            "text": "" if args.index_only else text,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                for completed_count, result in enumerate(pool.map(process, selected), 1):
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    if completed_count == 1 or completed_count % 10 == 0 or completed_count == len(selected):
                        handle.flush()
                        print(
                            f"progress={completed_count}/{len(selected)}",
                            flush=True,
                        )
        os.replace(temp_path, args.output)
    finally:
        temp_path.unlink(missing_ok=True)
    print(f"candidate_total={len(rows)} selected={len(selected)} offset={args.offset}")


if __name__ == "__main__":
    main()
