"""Use safe format-specific fallbacks for unresolved assessment records."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from math_subject_aliases import curriculum_from_codes, subject_hits


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    pages: list[str] = []
    for page in reader.pages:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                pages.append(page.extract_text() or "")
        except Exception as exc:  # one malformed page should not discard a PDF
            pages.append(f"[pdf page extraction error: {type(exc).__name__}]")
    return "\n\n".join(pages)


def hwpx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        sections = [
            info
            for info in archive.infolist()
            if info.filename.lower().startswith("contents/section")
            and info.filename.lower().endswith(".xml")
        ]
        total_size = sum(info.file_size for info in sections)
        if total_size > 250_000_000:
            raise ValueError(f"HWPX section payload too large: {total_size}")
        chunks: list[str] = []
        for info in sections:
            root = ET.fromstring(archive.read(info))
            chunks.append(" ".join(text.strip() for node in root.iter() if (text := node.text)))
        return "\n\n".join(chunks)


def fallback_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_text(path), "pypdf"
    if suffix == ".hwpx":
        return hwpx_text(path), "hwpx-xml"
    if suffix == ".zip":
        # Invalid archives are recorded explicitly; do not force extraction of
        # untrusted payloads merely to inflate a completeness count.
        with zipfile.ZipFile(path) as archive:
            return "\n".join(archive.namelist()), "zip-names"
    return "", "unsupported"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    with args.input_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("extract_status") != "ok":
                rows.append(record)

    def process(record: dict[str, object]) -> dict[str, object]:
        source = record.get("source") or {}
        path = args.project_root / str(source.get("saved_path", ""))
        previous_status = record.get("extract_status")
        try:
            text, method = fallback_text(path)
            status = "fallback_ok" if len(text.strip()) >= 300 else "fallback_short"
            error = ""
        except Exception as exc:
            text, method = f"[{type(exc).__name__}: {exc}]", "fallback_error"
            status, error = "fallback_failed", str(exc)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
        return {
            "source": source,
            "sha256": digest,
            "previous_status": previous_status,
            "fallback_method": method,
            "fallback_error": error,
            "extract_status": status,
            "char_count": len(text),
            "subject_hits": subject_hits(text),
            "curriculum_code_hints": curriculum_from_codes(text),
            "text": text,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for result in pool.map(process, rows):
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"fallback_total={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
