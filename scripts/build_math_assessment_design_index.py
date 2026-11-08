"""Add a source-backed topic and method index to a copy of a release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from contextlib import closing
from pathlib import Path


TOPICS = {
    "limits": r"함수의\s*극한|극한(?:값|과|의|을|이|에|\s)|연속성|(?:함수의|불)\s*연속|연속함수|사잇값\s*정리",
    "derivatives": r"도함수|미분계수|미분가능|미분법|미분(?:을|의|과|에|하|\s)|접선|변화율|평균값\s*정리|극대와\s*극소",
    "integrals": r"정적분|부정적분|적분법|(?<!미)적분(?:을|의|과|에|하|\s)",
}
METHODS = {
    "reasoning": r"증명|논증|반례|추론|(?:판단|성립|풀이)의\s*근거|오류(?:의\s*원인|를|\s*분석)",
    "graphing": r"그래프.{0,22}(?:그리|그려|개형|시각화|표현|작성|해석|분석)|시각화|(?:그린|그리는)\s*그래프",
    "problem-writing": r"(?:문제|문항)\s*(?:를\s*)?(?:만들|제작|출제|변형|구성)|문제\s*만들기",
    "modeling": r"모델링|수학적\s*모형|수학\s*모델\s*(?:구축|설계|수립|만들)",
    "data-analysis": r"(?:자료|데이터|측정값).{0,23}(?:분석|해석|비교)|(?:분석|해석)한\s*(?:자료|데이터)",
    "calculation": r"계산(?:하기|하|\s*및)|(?:극한값|기울기|방정식|넓이|부피|속도).{0,16}(?:구하|구한|구하기)",
    "problem-solving": r"문제\s*해결|문제(?:를|의)\s*풀|풀이\s*(?:제시|과정)|문제를\s*해결",
    "writing": r"서술|논술|글로\s*설명|근거를\s*써",
    "discussion": r"구술|발표|토론|토의",
    "inquiry": r"탐구|조사(?:하기|하|\s*및)",
    "process": r"포트폴리오|학습\s*일지|성찰\s*일지|과정\s*평가",
}
ARTIFACTS = {
    "report": r"보고서",
    "presentation": r"발표\s*(?:자료|문서)|슬라이드",
    "portfolio": r"포트폴리오|활동지|학습\s*일지",
    "product": r"포스터|인포그래픽|마인드맵|산출물",
}
STANDARDS = re.compile(r"12미적(?:I(?!I)|1)\s*-?\s*(0[123])\s*-\s*\d{2}")
STANDARD_TOPIC = {"01": "limits", "02": "derivatives", "03": "integrals"}

SCHEMA = """
CREATE TABLE design_index_items (
    item_id TEXT PRIMARY KEY REFERENCES assessment_items(item_id)
) WITHOUT ROWID;
CREATE TABLE design_index_tags (
    item_id TEXT NOT NULL REFERENCES design_index_items(item_id),
    axis TEXT NOT NULL CHECK(axis IN ('topic','method','artifact')),
    tag TEXT NOT NULL,
    source_field TEXT NOT NULL CHECK(source_field IN ('title','overview','method','standard')),
    evidence TEXT NOT NULL CHECK(length(evidence) BETWEEN 1 AND 100),
    PRIMARY KEY(item_id, axis, tag)
) WITHOUT ROWID;
CREATE INDEX design_index_lookup ON design_index_tags(axis, tag, item_id);
"""


def classify(title: str, overview: str, method: str, standards: list[str]) -> list[tuple[str, str, str, str]]:
    fields = [(name, " ".join(unicodedata.normalize("NFKC", value).split())) for name, value in (
        ("title", title), ("overview", overview), ("method", method),
    )]
    evidence: list[tuple[str, str, str, str]] = []
    for axis, rules in (("topic", TOPICS), ("method", METHODS), ("artifact", ARTIFACTS)):
        for tag, rule in rules.items():
            eligible = fields if axis == "method" and tag in {"writing", "discussion"} else fields[:2]
            for field, value in eligible:
                match = re.search(rule, value)
                if match:
                    evidence.append((axis, tag, field, match.group().strip()))
                    break
    if not any(axis == "topic" for axis, _, _, _ in evidence):
        codes = [(match[1], match.group()) for code in standards
                 for match in STANDARDS.finditer(unicodedata.normalize("NFKC", code))]
        if len({chapter for chapter, _ in codes}) == 1:
            chapter, code = codes[0]
            evidence.append(("topic", STANDARD_TOPIC[chapter], "standard", code))
    return evidence


def readonly(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro&immutable=1"


def build(source: Path, semester: Path, output: Path, expected_items: int | None) -> dict:
    if output.exists():
        raise SystemExit("Choose a fresh output database to preserve the original release candidate.")
    with closing(sqlite3.connect(readonly(source), uri=True)) as baseline, closing(sqlite3.connect(output, uri=True)) as db:
        baseline.backup(db)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("ATTACH DATABASE ? AS term", (readonly(semester),))
        rows = db.execute("""SELECT i.item_id, i.title, i.overview, i.method, i.standards_json
            FROM main.assessment_items i
            JOIN main.cases c USING (case_id)
            JOIN term.assessment_items ti ON ti.item_id=i.item_id AND ti.case_id=i.case_id
            WHERE c.subject='미적분Ⅰ' AND c.semesters_json='[2]'
              AND i.extraction_status='bounded' AND i.title_basis IN ('table','heading')
              AND ti.extraction_status='bounded' AND ti.title_basis IN ('table','heading')
              AND c.title_basis='source_detail'
            ORDER BY i.item_id""").fetchall()
        if not rows or (expected_items is not None and len(rows) != expected_items):
            raise SystemExit(f"Pilot scope check failed: {len(rows)} items, expected {expected_items}")
        db.executescript(SCHEMA)
        counts: Counter[str] = Counter()
        coverage: Counter[str] = Counter()
        with db:
            for item_id, title, overview, method, standards in rows:
                db.execute("INSERT INTO design_index_items VALUES (?)", (item_id,))
                evidence = classify(title, overview, method, json.loads(standards))
                db.executemany("INSERT INTO design_index_tags VALUES (?, ?, ?, ?, ?)",
                               [(item_id, *tag) for tag in evidence])
                axes = {axis for axis, _, _, _ in evidence}
                coverage.update(axes)
                coverage["both"] += {"topic", "method"}.issubset(axes)
                counts.update(f"{axis}:{tag}" for axis, tag, _, _ in evidence)
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise SystemExit("Index candidate failed SQLite integrity checks")
    return {"scope": "2026학년도 2학기 미적분Ⅰ", "total_items": len(rows), "coverage": dict(coverage),
            "tag_counts": dict(sorted(counts.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--semester-detail", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-items", type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "data" / "derived"
    if not all(path.resolve().is_relative_to(root) for path in (args.output, args.report)):
        parser.error("output and report must be within data/derived")
    if args.output.resolve() == args.report.resolve() or args.report.exists():
        parser.error("choose a distinct, fresh report path")
    if not args.database.is_file() or not args.semester_detail.is_file():
        parser.error("both audited inputs must exist")
    result = build(args.database, args.semester_detail, args.output, args.expected_items)
    for key, path in (("input_sha256", args.database), ("semester_sha256", args.semester_detail),
                      ("output_sha256", args.output)):
        with path.open("rb") as stream:
            result[key] = hashlib.file_digest(stream, "sha256").hexdigest()
    with args.report.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
