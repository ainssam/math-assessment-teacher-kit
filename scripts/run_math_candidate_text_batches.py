"""Run remaining full-text candidate batches sequentially overnight."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--input-jsonl", type=Path)
    parser.add_argument("--output-prefix", default="math_subject_candidate_text")
    parser.add_argument("--start-offset", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--total", type=int, default=8297)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--wait-for", type=int, default=0)
    args = parser.parse_args()

    root = args.project_root
    input_jsonl = args.input_jsonl or (root / "data" / "derived" / "math_subject_candidate_index.jsonl")
    script = root / "scripts" / "extract_math_candidate_text.py"
    kordoc = root / "scripts" / "kordoc-fixed.cmd"
    py = Path(sys.executable)
    log = root / "data" / "derived" / "math_subject_candidate_text_batches.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    if args.wait_for:
        gate = root / "data" / "derived" / f"{args.output_prefix}_{args.wait_for:04d}.jsonl"
        gate_limit = min(args.batch_size, args.total - args.wait_for)
        while row_count(gate) < gate_limit:
            time.sleep(20)

    for offset in range(args.start_offset, args.total, args.batch_size):
        limit = min(args.batch_size, args.total - offset)
        output = root / "data" / "derived" / f"{args.output_prefix}_{offset:04d}.jsonl"
        if row_count(output) >= limit:
            continue
        command = [
            str(py),
            str(script),
            "--input-jsonl",
            str(input_jsonl),
            "--project-root",
            str(root),
            "--kordoc",
            str(kordoc),
            "--output",
            str(output),
            "--offset",
            str(offset),
            "--limit",
            str(limit),
            "--workers",
            str(args.workers),
        ]
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        result = subprocess.run(command, cwd=root, text=True, capture_output=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"offset": offset, "limit": limit, "started": started, "returncode": result.returncode, "stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]}, ensure_ascii=False) + "\n")
        if result.returncode != 0:
            time.sleep(10)
            retry = subprocess.run(command, cwd=root, text=True, capture_output=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"offset": offset, "limit": limit, "retry": True, "returncode": retry.returncode, "stdout": retry.stdout[-1000:], "stderr": retry.stderr[-1000:]}, ensure_ascii=False) + "\n")
            if retry.returncode != 0:
                raise SystemExit(f"batch failed at offset {offset}")


if __name__ == "__main__":
    main()
