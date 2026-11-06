"""Extract bounded batches of filename-confirmed math assessment plans.

The extractor is deterministic and produces provenance-rich JSONL for a later
model pass. It intentionally skips ``unknown`` and generic ``수학`` filename
matches until a content scan is designed for mixed all-subject documents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from math_subject_aliases import curriculum_from_codes, subject_hits


def extract_pdf_text(path: Path) -> str:
    """Use the PDF text layer when kordoc fails or returns an empty document."""
    try:
        import fitz

        fitz.TOOLS.mupdf_display_errors(False)
        with fitz.open(path) as document:
            return "\n\n".join(page.get_text("text") for page in document)
    except Exception:
        return ""


def extract(path: Path, kordoc: Path, cwd: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".zip":
        parts: list[str] = []
        statuses: list[str] = []
        with tempfile.TemporaryDirectory(prefix="math_plan_zip_") as temp:
            root = Path(temp)
            try:
                with zipfile.ZipFile(path) as archive:
                    members = [
                        info for info in archive.infolist()
                        if not info.is_dir()
                        and Path(info.filename).suffix.lower() in {".hwp", ".hwpx", ".pdf", ".docx", ".xlsx"}
                    ]
                    if len(members) > 400 or sum(info.file_size for info in members) > 512 * 1024**2:
                        return "[zip extraction limit exceeded]", "failed"
                    for index, info in enumerate(members):
                        suffix = Path(info.filename).suffix.lower()
                        target = root / f"{index:05}{suffix}"
                        target.write_bytes(archive.read(info))
                        child, status = extract(target, kordoc, cwd)
                        statuses.append(status)
                        parts.append(f"[zip:{info.filename}][{status}]\n{child}")
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                return f"[zip error: {exc}]", "failed"
        text = "\n\n".join(parts)
        if not statuses or all(status == "failed" for status in statuses):
            return text, "failed"
        return text, "ok" if all(status == "ok" for status in statuses) else "short"
    if path.suffix.lower() == ".pdf":
        direct_pdf_text = extract_pdf_text(path)
        if len(direct_pdf_text.strip()) >= 300:
            return direct_pdf_text, "ok"
    with tempfile.TemporaryDirectory(prefix="math_plan_batch_") as temp:
        output = Path(temp) / "parsed.md"
        try:
            command = [str(kordoc), str(path), "--silent", "-o", str(output)]
            if kordoc.suffix.lower() in {".js", ".mjs"}:
                command.insert(0, "node")
            elif kordoc.name.lower() == "kordoc-fixed.cmd":
                local_cli = cwd / "node_modules" / "kordoc" / "dist" / "cli.js"
                if not local_cli.exists():
                    return f"[kordoc CLI missing: {local_cli}]", "failed"
                command = [
                    "node",
                    str(local_cli),
                    str(path),
                    "--silent",
                    "-o",
                    str(output),
                ]
            completed = subprocess.run(
                command,
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
            if path.suffix.lower() == ".pdf":
                fallback = extract_pdf_text(path)
                if len(fallback.strip()) >= 300:
                    return fallback, "ok"
            return f"[kordoc exit={completed.returncode}: {completed.stderr[:500]}]", "failed"
        text = output.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 300 and path.suffix.lower() == ".pdf":
            fallback = extract_pdf_text(path)
            if len(fallback.strip()) > len(text.strip()):
                text = fallback
        return text, "ok" if len(text.strip()) >= 300 else "short"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--kordoc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--include-generic", action="store_true", help="include generic all-subject/grade plan filenames")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--index-only", action="store_true", help="store subject/status metadata without full text")
    args = parser.parse_args()

    candidates: list[dict[str, str]] = []
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("subject_canonical") in {"unknown", "수학"}:
                if not args.include_generic:
                    continue
                if not re.search(r"교수|평가.?계획|전과목|교과별|학년별", row.get("candidate_name", "")):
                    continue
            if not args.include_generic and row.get("match_type") != "filename_alias":
                continue
            candidates.append(row)
    candidates.sort(key=lambda r: (r["subject_canonical"], r["school_name"], r["candidate_name"]))
    selected = candidates[args.offset : args.offset + args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    def process(row: dict[str, str]) -> dict[str, object]:
        path = args.project_root / row["saved_path"]
        if not path.exists():
            text, status, digest = f"[missing: {path}]", "missing", ""
        else:
            text, status = extract(path, args.kordoc, args.project_root)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hits = subject_hits(text)
        codes = curriculum_from_codes(text)
        return {
            "source": row,
            "sha256": digest,
            "extract_status": status,
            "char_count": len(text),
            "subject_hits": hits,
            "curriculum_code_hints": codes,
            "text": "" if args.index_only else text,
        }

    with args.output.open("w", encoding="utf-8") as handle:
        if args.workers > 1:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                records = pool.map(process, selected)
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            for row in selected:
                handle.write(json.dumps(process(row), ensure_ascii=False) + "\n")
    print(f"candidate_total={len(candidates)} selected={len(selected)} offset={args.offset}")


if __name__ == "__main__":
    main()
