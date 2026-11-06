# ruff: noqa: E501
"""Export one source-bounded assessment item as a printable PDF."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import subprocess
import tempfile
import zlib
from pathlib import Path

CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def printable_html(row: sqlite3.Row) -> str:
    source_html = zlib.decompress(row["source_html_zlib"]).decode("utf-8")
    rubric_html = zlib.decompress(row["rubric_html_zlib"]).decode("utf-8")
    standards = json.loads(str(row["standards_json"]))
    facts = [
        ("학교", str(row["school_name"])),
        ("지역", str(row["region"])),
        ("교육과정·과목", f"{row['curriculum']} 개정 · {row['subject']}"),
        ("수행평가명", str(row["title_raw"])),
        ("평가 개요", str(row["overview"])),
        ("평가 방법", str(row["method"])),
        ("시기", str(row["timing"])),
        ("만점", str(row["score"])),
        ("반영·배점", str(row["weight"])),
        ("성취기준", ", ".join(map(str, standards))),
    ]
    fact_rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in facts
        if value.strip()
    )
    rubric = (
        "<section class='rubric'><h2>채점 기준 원문 표</h2>"
        "<p>수행평가 원문에 포함된 채점 기준 표를 찾기 쉽게 다시 표시합니다.</p>"
        f"{rubric_html}</section>"
        if rubric_html.strip()
        else ""
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{html.escape(str(row['title']))}</title>
<style>
@page {{ size: A4 landscape; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: #16231d; font-family: "Noto Sans KR", "Malgun Gothic", sans-serif; font-size: 9pt; line-height: 1.55; }}
header {{ margin-bottom: 7mm; border-bottom: 1px solid #9aa9a1; }}
header p {{ margin: 0 0 2mm; color: #4d685a; font-weight: 700; }}
h1 {{ margin: 0 0 4mm; font-size: 18pt; }}
h2 {{ margin: 7mm 0 3mm; color: #173e2d; font-size: 13pt; }}
.notice {{ padding: 3mm; border: 1px solid #c7d7ce; background: #f2f7f4; }}
.facts {{ width: 100%; margin: 5mm 0; border-collapse: collapse; }}
.facts th, .facts td {{ padding: 2.3mm; border: 1px solid #a7b3ac; vertical-align: top; text-align: left; }}
.facts th {{ width: 32mm; color: #173e2d; background: #edf4ef; }}
.source table, .rubric table {{ width: 100%; margin: 4mm 0; border-collapse: collapse; break-inside: avoid; }}
.source th, .source td, .rubric th, .rubric td {{ min-width: 12mm; padding: 1.8mm; border: 1px solid #87978e; vertical-align: top; overflow-wrap: anywhere; }}
.source th, .rubric th {{ color: #173e2d; background: #edf4ef; }}
.source p {{ white-space: pre-wrap; }}
.rubric {{ margin-top: 10mm; padding-top: 4mm; border-top: 2px solid #173e2d; break-before: page; }}
.rubric > p {{ color: #52675c; }}
</style></head><body>
<header><p>수학 수행평가 설계 도우미 · 원문 추출본 PDF</p><h1>{html.escape(str(row['title']))}</h1></header>
<p class="notice">원문 문구와 추출 과정에 남아 있는 표 병합 구조를 보존한 추출본입니다. 원문 지면 배치·도형은 달라질 수 있습니다.</p>
<table class="facts">{fact_rows}</table>
<main class="source"><h2>수행평가 원문 구간</h2>{source_html}</main>
{rubric}
</body></html>"""


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("item_id")
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser", type=Path)
    args = parser.parse_args()
    browser = args.browser or next(
        (candidate for candidate in CHROME_CANDIDATES if candidate.is_file()), None
    )
    if browser is None or not browser.is_file():
        raise SystemExit("Chrome or Edge executable not found")
    if not args.database.is_file():
        raise SystemExit(f"detail database not found: {args.database}")
    with sqlite3.connect(
        f"file:{args.database.resolve().as_posix()}?mode=ro", uri=True
    ) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT item.*, cases.curriculum, cases.subject, cases.school_name,
                   cases.region
            FROM assessment_items item
            JOIN cases ON cases.case_id = item.case_id
            WHERE item.item_id = ?
            """,
            (args.item_id,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"assessment item not found: {args.item_id}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="assessment-pdf-") as temporary_directory:
        source = Path(temporary_directory) / "assessment.html"
        source.write_text(printable_html(row), encoding="utf-8")
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={args.output.resolve()}",
            source.resolve().as_uri(),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0 or not args.output.is_file():
            raise SystemExit(
                f"PDF export failed ({completed.returncode}): {completed.stderr.strip()}"
            )
    print(
        json.dumps(
            {
                "item_id": args.item_id,
                "output": str(args.output.resolve()),
                "bytes": args.output.stat().st_size,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
