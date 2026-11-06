"""Extract a small, provenance-preserving text sample for parser validation.

The full corpus stays untouched.  This creates only a bounded JSONL sample so a
later Luna call can be tested on real assessment-plan layouts before scaling.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def extract(path: Path, kordoc: Path, cwd: Path) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="math_plan_") as temp:
        output = Path(temp) / "parsed.md"
        try:
            completed = subprocess.run(
                [str(kordoc), str(path), "--silent", "-o", str(output)],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"[{type(exc).__name__}: {exc}]", "failed"
        if completed.returncode or not output.exists():
            return f"[kordoc exit={completed.returncode}: {completed.stderr[:500]}]", "failed"
        text = output.read_text(encoding="utf-8", errors="replace")
        return text, "ok" if len(text.strip()) >= 300 else "short"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--kordoc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-subject", type=int, default=2)
    args = parser.parse_args()

    selected: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            subject = row.get("subject_canonical", "unknown")
            if subject in {"unknown", "수학"} or row.get("curriculum_candidate") != "2022_candidate":
                continue
            if counts.get(subject, 0) >= args.per_subject:
                continue
            path = args.external_root / row["saved_path"]
            if not path.exists():
                continue
            counts[subject] = counts.get(subject, 0) + 1
            selected.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        for row in selected:
            path = args.external_root / row["saved_path"]
            text, status = extract(path, args.kordoc, args.external_root)
            record = {
                "source": {k: row[k] for k in ("curriculum_candidate", "school_code", "school_name", "candidate_name", "subject_canonical", "saved_path", "final_url")},
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "extract_status": status,
                "char_count": len(text),
                "text": text,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"sample_rows={len(selected)}")
    print("subjects=" + ",".join(f"{key}:{value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
