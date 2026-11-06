"""Audit subject-group coverage of a collected reference corpus.

This is a deterministic triage report. It does not judge educational quality;
it identifies where a teacher should inspect or collect more source material.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SUBJECT_GROUPS: dict[str, tuple[str, ...]] = {
    "국어": ("국어", "독서", "문학", "화법", "작문", "언어와 매체", "매체"),
    "수학": ("수학", "대수", "미적분", "기하", "확률", "통계"),
    "영어": ("영어", "영문"),
    "사회": ("사회", "역사", "한국사", "지리", "윤리", "도덕", "경제", "정치", "법", "사회문화"),
    "과학": ("과학", "물리", "화학", "생명", "지구과학", "환경", "생태"),
    "체육": ("체육", "스포츠", "운동", "건강"),
    "예술": ("음악", "미술", "예술", "디자인", "공연"),
    "기술·가정": ("기술가정", "기술·가정", "가정", "공학", "생활과학"),
    "정보·AI": ("정보", "인공지능", "AI", "데이터", "소프트웨어", "코딩"),
    "제2외국어·한문": ("중국어", "일본어", "프랑스어", "독일어", "스페인어", "러시아어", "아랍어", "베트남어", "한문"),
    "교양·진로": ("진로", "철학", "논리", "심리", "교육", "보건", "종교", "교양"),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def searchable(record: dict[str, Any]) -> str:
    fields = ("title", "subjects", "notes", "category", "axis")
    return " ".join(str(record.get(field, "")) for field in fields).lower()


def matches(record: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    text = searchable(record)
    return any(keyword.lower() in text for keyword in keywords)


def rating(catalog_count: int, downloaded_count: int) -> str:
    if catalog_count < 3 or downloaded_count < 2:
        return "매우 부족"
    if catalog_count < 6 or downloaded_count < 4:
        return "부족"
    if downloaded_count < 8:
        return "보강 권장"
    return "기본 충족"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--document-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    catalog: list[dict[str, Any]] = json.loads(args.catalog.read_text(encoding="utf-8"))
    documents = [row for row in read_jsonl(args.document_index) if row.get("text_status") == "extracted"]
    catalog_by_id = {row.get("id"): row for row in catalog}

    unique_documents: dict[str, dict[str, Any]] = {}
    source_ids_by_hash: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        digest = document.get("sha256")
        if not digest:
            continue
        unique_documents.setdefault(digest, document)
        if document.get("source_id"):
            source_ids_by_hash[digest].add(str(document["source_id"]))

    coverage = []
    for group, keywords in SUBJECT_GROUPS.items():
        catalog_ids = {str(row.get("id")) for row in catalog if matches(row, keywords)}
        downloaded_hashes = {
            digest
            for digest, source_ids in source_ids_by_hash.items()
            if source_ids & catalog_ids
        }
        coverage.append({
            "subject_group": group,
            "catalog_records": len(catalog_ids),
            "downloaded_documents": len(downloaded_hashes),
            "rating": rating(len(catalog_ids), len(downloaded_hashes)),
        })

    axis_counts = Counter(str(row.get("axis") or "미분류") for row in catalog)
    represented_ids = {source_id for ids in source_ids_by_hash.values() for source_id in ids}
    missing_priority_a = [
        {"id": row.get("id"), "title": row.get("title"), "page_url": row.get("page_url")}
        for row in catalog
        if row.get("priority") == "A" and str(row.get("id")) not in represented_ids
    ]
    report = {
        "catalog_records": len(catalog),
        "indexed_document_rows": len(documents),
        "unique_downloaded_documents": len(unique_documents),
        "subject_coverage": coverage,
        "axis_counts": dict(axis_counts),
        "missing_priority_a_count": len(missing_priority_a),
        "missing_priority_a": missing_priority_a,
        "method_note": "키워드 기반 1차 공백 점검이며 교육적 품질 판정이 아님",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 참고자료 교과군 공백 점검",
        "",
        f"- 카탈로그: {len(catalog)}건",
        f"- 본문 추출 문서 행: {len(documents)}건",
        f"- SHA-256 기준 고유 문서: {len(unique_documents)}건",
        f"- 원문 미확보 A등급 자료: {len(missing_priority_a)}건",
        "",
        "| 교과군 | 목록 | 실제 문서 | 1차 판정 |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| {row['subject_group']} | {row['catalog_records']} | {row['downloaded_documents']} | {row['rating']} |"
        for row in coverage
    )
    lines.extend([
        "",
        "> 이 표는 제목·교과·비고의 키워드와 실제 확보 문서를 연결한 수집 공백 지표다. 최종 사례 품질은 성취기준 문장, 탐구 질문, 방법, 산출물, 원문 페이지를 교사가 확인한 뒤 결정한다.",
    ])
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"coverage": coverage, "missing_priority_a": len(missing_priority_a)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
