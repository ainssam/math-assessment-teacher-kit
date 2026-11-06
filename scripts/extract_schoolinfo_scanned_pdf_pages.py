"""Make page-numbered OCR evidence for source PDFs missing a text layer."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import subprocess

import fitz


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "schoolinfo"
DERIVED = ROOT / "data" / "derived"


def extract_pages(row: dict, ocr: Path, output: Path, page_limit: int) -> dict:
    source = (ROOT / row["saved_path"]).resolve()
    if not source.is_relative_to(RAW) or source.suffix.lower() != ".pdf":
        raise ValueError("OCR source must be a preserved Schoolinfo PDF")
    with source.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != row["sha256"]:
        raise ValueError(f"OCR source hash differs: {row['saved_path']}")
    result_path = output / f"{digest}.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    pages = []
    page_count = 0
    error = ""
    try:
        with fitz.open(source) as document:
            page_count = len(document)
            if document.needs_pass or not page_count:
                raise ValueError("PDF has no readable pages")
            selected = min(page_count, page_limit) if page_limit else page_count
            for index in range(selected):
                page = document[index]
                text = page.get_text("text").strip()
                status = "text_layer"
                if len(text) < 150:
                    try:
                        image = page.get_pixmap(dpi=180, colorspace=fitz.csGRAY).tobytes("png")
                        result = subprocess.run(
                            [str(ocr), "stdin", "stdout", "-l", "kor+eng", "--psm", "6"],
                            input=image, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                            env=environment, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                        text = result.stdout.decode("utf-8").strip()
                        status = "ocr" if text else "no_text"
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        text, status = "", type(exc).__name__
                pages.append({"page": index + 1, "status": status, "text": text})
    except (OSError, ValueError, RuntimeError) as exc:
        error = type(exc).__name__
    payload = {"source": row, "page_count": page_count, "pages": pages, "document_error": error}
    temporary = result_path.with_suffix(".partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(result_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--tesseract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--math-names", action="store_true")
    parser.add_argument("--page-limit", type=int, default=0, help="0 processes the whole source")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(DERIVED) or output == DERIVED or args.page_limit < 0:
        parser.error("output must be a derived-data subdirectory and page limit must be nonnegative")
    engine = args.tesseract.resolve()
    if not engine.is_file():
        parser.error("tesseract executable does not exist")
    output.mkdir(parents=True, exist_ok=False)
    originals = {}
    with args.decisions.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["extract_status"] == "ok" or Path(row["saved_path"]).suffix.lower() != ".pdf":
                continue
            if row["semester_status"] in {"other_semester", "academic_year_conflict"}:
                continue
            if args.math_names and row.get("subject_canonical") in {"", "unknown", None}:
                continue
            originals.setdefault(row["sha256"], row)
    print(f"selected_pdfs={len(originals)}", flush=True)
    overview = []
    worker = partial(extract_pages, ocr=engine, output=output, page_limit=args.page_limit)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, result in enumerate(pool.map(worker, originals.values()), 1):
            source = result["source"]
            overview.append({"sha256": source["sha256"], "school_name": source["school_name"],
                             "page_count": result["page_count"], "pages_attempted": len(result["pages"]),
                             "pages_with_text": sum(bool(page["text"]) for page in result["pages"]),
                             "document_error": result["document_error"]})
            print(f"ocr_documents={index}/{len(originals)} pages={len(result['pages'])}", flush=True)
    (output / "summary.json").write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
