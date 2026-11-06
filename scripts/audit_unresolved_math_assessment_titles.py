"""Read-only title recovery audit for unresolved math-assessment bundles.

The detail catalogue deliberately keeps ambiguous source bundles instead of
inventing a performance-assessment title.  This utility inspects only those
bundles, including flattened PDF/HWP table text, and writes a review queue.
It never changes the SQLite catalogue or the source files.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
import sys
import zlib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_math_assessment_publish_db import (
    TASK_SIGNAL_RE,
    TASK_TITLE_END_RE,
    normalize_task_name,
    task_name_is_rejected,
)
from scripts.math_assessment_detail_parser import (
    EXPECTED_STANDARD_PREFIXES,
    compact_text,
    subject_code_key,
)

SUPPORT_MARKER_RE = re.compile(
    r"성취\s*기준|반영\s*비율|배점|만점|평가\s*방법|평가\s*시기|"
    r"채점\s*기준|평가\s*요소|세부\s*기준|평가\s*개요"
)
TITLE_LABEL_RE = re.compile(
    r"^(?P<label>수행\s*평가\s*(?:과제\s*)?(?:명|영역)|수행\s*과제\s*(?:명)?|"
    r"평가\s*과제\s*명?|평가\s*영역\s*명?|과제\s*명|평가\s*명)\s*[:：|]?\s*(?P<value>.*)$"
)
INLINE_TITLE_LABEL_RE = re.compile(
    r"(?P<label>수행\s*평가\s*(?:과제\s*)?(?:명|영역)|수행\s*과제\s*(?:명)?|"
    r"평가\s*과제\s*명?|평가\s*영역\s*명?|과제\s*명|평가\s*명)\s*[:：|]?\s*"
    r"(?P<value>.{2,180})"
)
STOP_LABEL_RE = re.compile(
    r"\s+(?:단원\s*명|관련\s*단원|성취\s*기준|평가\s*방법|평가\s*시기|"
    r"반영\s*비율|배점|만점|평가\s*요소|채점\s*기준|세부\s*기준|평가\s*개요|"
    r"영역\s*만점|학기|점수)\b"
)
MATH_CONTEXT_RE = re.compile(
    r"수학|함수|수열|방정식|부등식|도형|좌표|미분|적분|극한|확률|통계|"
    r"기하|대수|행렬|벡터|복소수|지수|로그|삼각|경우의\s*수|집합|명제"
)
OTHER_SUBJECT_RE = re.compile(
    r"국어|화법|작문|영어|한국사|통합사회|통합과학|물리학|화학|"
    r"생명과학|지구과학|세계사|동아시아사|윤리와\s*사상|생활과\s*윤리|"
    r"음악|미술|체육|프로그래밍"
)
STANDARD_CODE_RE = re.compile(
    r"\[\s*((?:10|12)(?:\s*-\s*)?[^\]\-]{1,20})\s*-\s*\d"
)
GENERIC_LABEL_VALUE_RE = re.compile(
    r"^(?:방법[·・](?:내용|과정|메타인지)|기본점수|영역만점|평가방법|평가시기)$"
)
AUTO_PROMOTION_REJECT_RE = re.compile(
    r"(?:\d+차\s*시험|교육과정|성취기준|평가방법|평가요소|채점기준|기본점수|"
    r"반영비율|영역만점|수행평가\s*세부|내용\s*요소|성\s*취\s*기\s*준|~|"
    r"정기\s*고사|프로젝트\.?\s*실습|방법[·・]|영역\s*및\s*(?:방법|비율))"
)
INCOMPLETE_TITLE_RE = re.compile(
    r"(?:하여|하며|하고|과정|능력|평가함|수행함|되도록|경우|의|와|과|및|을|를|에|한)$"
)
CONCATENATED_TITLE_END_RE = re.compile(
    r"(?:보고서\s*작성하기|문제\s*제작하기|문항\s*제작하기|"
    r"탐구하기|만들기|제작하기|분석하기|설명하기|해결하기|증명하기|"
    r"표현하기|정리하기|그리기|글쓰기|모델링하기|포트폴리오|프로젝트|발표)"
    r"(?=\s+[가-힣])"
)
TABLE_HEADER_FRAGMENT_RE = re.compile(
    r"^(?:및\s*(?:비율|방법|구술)|\d+차\s*\(?\s*(?:중간|기말)\s*\)?|"
    r"정기\s*고사|프로젝트\.?\s*실습|방법[·・])$"
)
TITLE_FRAGMENT_RE = re.compile(
    r"^(?:[•·∙▪・⚪○□■※]+\s*)?(?:포트폴리오|작성하기|주제\s*선정|"
    r"\d+\s*단계(?:\s*\([^)]*\))?\s*[:：]?.*|[ⅠⅡⅢⅣV]+\.?\s*)$"
)


@dataclass(frozen=True)
class TitleCandidate:
    case_id: str
    curriculum: str
    subject: str
    school_name: str
    region: str
    source_format: str
    boundary_status: str
    candidate: str
    raw_candidate: str
    label: str
    detection: str
    confidence: str
    confidence_score: int
    subject_alignment: str
    subject_mentioned: bool
    math_context: bool
    other_subject_signal: bool
    support_marker_count: int
    explicit_name_label: bool
    title_looks_complete: bool
    source_order: int
    source_excerpt: str


def layout_text(source_html: str) -> str:
    """Keep likely PDF/HWP table cells and rows distinct in a plain-text view."""

    value = html.unescape(source_html)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:tr|p|div|li|h[1-6]|table)\s*>", "\n", value, flags=re.I)
    value = re.sub(r"</?t[dh]\b[^>]*>", "\t", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value).replace("\r", "")
    lines = []
    for raw_line in value.split("\n"):
        cells = [re.sub(r"\s+", " ", cell).strip() for cell in raw_line.split("\t")]
        cells = [cell for cell in cells if cell]
        if cells:
            lines.append("\t".join(cells))
    return "\n".join(lines)


def clean_raw_candidate(value: str) -> str:
    value = STOP_LABEL_RE.split(value, maxsplit=1)[0]
    value = value.split("\t", maxsplit=1)[0]
    value = re.sub(r"\s+", " ", value).strip(" |:：-–—")
    # School plans often use a sentence-length ``수행 과제`` as the official
    # name.  Truncating the audit candidate made an exact source-authored title
    # look unsupported even though the complete value was present in the cell.
    # Keep the same bounded length used by the detail catalogue instead.
    return value[:500]


def split_concatenated_titles(value: str) -> list[str]:
    """Split only adjacent complete task-name endings from flattened table text."""

    parts: list[str] = []
    start = 0
    for match in CONCATENATED_TITLE_END_RE.finditer(value):
        tail = value[match.end() :].lstrip()
        # ``문제 만들기 및 풀이하기`` is one source-authored task name,
        # not two titles accidentally flattened together.  Split only when
        # the next phrase is not a connective continuation.
        if re.match(r"^(?:및|와|과|하고|하여|후|뒤|또는)(?:\s|$)", tail):
            continue
        parts.append(value[start : match.end()].strip())
        start = match.end()
    if parts:
        parts.append(value[start:].strip())
    return [part for part in parts if part] or [value]


def source_excerpt(text: str, position: int) -> str:
    start = max(0, position - 100)
    end = min(len(text), position + 340)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def candidate_rows(text: str) -> list[tuple[str, str, str, int]]:
    """Return direct label/value candidates before using looser inline text."""

    results: list[tuple[str, str, str, int]] = []
    for offset, line in enumerate(text.splitlines()):
        cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        for cell_index, cell in enumerate(cells):
            match = TITLE_LABEL_RE.match(cell)
            if not match:
                continue
            value = match.group("value")
            if not value and cell_index + 1 < len(cells):
                value = cells[cell_index + 1]
            value = clean_raw_candidate(value)
            parts = split_concatenated_titles(value) if explicit_name_label(
                match.group("label")
            ) else [value]
            for part in parts:
                if part:
                    results.append((match.group("label"), part, "table_row", offset))
    if results:
        return results
    for offset, line in enumerate(text.splitlines()):
        match = INLINE_TITLE_LABEL_RE.search(line)
        if match:
            value = clean_raw_candidate(match.group("value"))
            parts = split_concatenated_titles(value) if explicit_name_label(
                match.group("label")
            ) else [value]
            for part in parts:
                if part:
                    results.append((match.group("label"), part, "flattened_line", offset))
    return results


def candidate_confidence(
    *,
    candidate: str,
    detection: str,
    alignment: str,
    subject_mentioned: bool,
    math_context: bool,
    other_subject_signal: bool,
    support_marker_count: int,
    explicit_name_label: bool,
    title_looks_complete: bool,
) -> tuple[str, int]:
    score = 0
    score += 3 if detection == "table_row" else 1
    score += min(support_marker_count, 3)
    score += 3 if alignment == "expected" else 0
    score += 1 if subject_mentioned else 0
    score += 1 if math_context else 0
    score += 1 if TASK_SIGNAL_RE.search(candidate) else 0
    score += 2 if explicit_name_label else 0
    score += 2 if title_looks_complete else 0
    score -= 5 if alignment in {"other", "mixed"} else 0
    score -= 3 if other_subject_signal and not MATH_CONTEXT_RE.search(candidate) else 0
    auto_promotable = (
        detection == "table_row"
        and alignment == "expected"
        and not other_subject_signal
        and explicit_name_label
        and title_looks_complete
        and bool(TASK_SIGNAL_RE.search(candidate))
        and not AUTO_PROMOTION_REJECT_RE.search(candidate)
        and not TITLE_FRAGMENT_RE.fullmatch(candidate)
    )
    return (
        "high" if auto_promotable and score >= 8 else "review" if score >= 3 else "reject",
        score,
    )


def standard_alignment(value: str, subject: str) -> str:
    """Require nearby achievement codes to agree with the selected subject."""

    prefixes = tuple(subject_code_key(prefix) for prefix in EXPECTED_STANDARD_PREFIXES.get(subject, ()))
    codes = [subject_code_key(match) for match in STANDARD_CODE_RE.findall(value)]
    if not codes:
        return "unknown"
    expected = any(code.startswith(prefix) for code in codes for prefix in prefixes)
    other = any(
        not any(code.startswith(prefix) for prefix in prefixes)
        for code in codes
    )
    if expected and other:
        return "mixed"
    return "expected" if expected else "other"


def explicit_name_label(label: str) -> bool:
    compact = compact_text(label)
    # "평가 과제" is the field name used by many 2022 curriculum plans for
    # the actual performance-assessment title.  Unlike "수행 과제" (which
    # often contains a long instruction), this field is immediately followed
    # by the task name in the original table.  Treat it as an explicit title
    # field, but keep the separate subject/traceability checks below.
    return compact.endswith("명") or compact in {
        "수행평가영역",
        "평가영역",
        "평가과제",
    }


def title_looks_complete(candidate: str) -> bool:
    if TASK_TITLE_END_RE.search(candidate):
        return True
    # A small number of plans name a task with an explicit "… 평가" or
    # "… 점검" ending.  Other short table cells can be curriculum ranges or
    # an instruction fragment, so shortness alone must not make them titles.
    return bool(
        TASK_SIGNAL_RE.search(candidate)
        and re.search(r"(?:평가|점검|퀴즈)$", candidate)
        and not INCOMPLETE_TITLE_RE.search(candidate)
    )


def normalize_candidate(raw_candidate: str) -> str:
    """Remove only table separators and field prefixes introduced by extraction."""

    candidate = normalize_task_name(raw_candidate)
    candidate = re.sub(r"^\s*(?:\d+|[가-하])\s*/\s*", "", candidate)
    candidate = re.sub(r"^\s*/+\s*|\s*/+\s*$", "", candidate)
    candidate = re.sub(r"^수행\s*평가\s*[-–—]\s*", "", candidate)
    candidate = re.sub(r"^\s*[-–—]\s*", "", candidate)
    return re.sub(r"\s+", " ", candidate).strip()


def unresolved_cases(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT c.case_id, c.curriculum, c.subject, c.school_name, c.region,
               s.source_format, s.boundary_status
        FROM cases c
        JOIN case_detail_status s USING (case_id)
        WHERE c.title_basis = 'source_detail_bundle_review'
          AND s.detected_title_count = 0
        ORDER BY c.case_id
        """
    ).fetchall()


def inspect_case(connection: sqlite3.Connection, row: sqlite3.Row) -> list[TitleCandidate]:
    source_html = "\n".join(
        zlib.decompress(bytes(item[0])).decode("utf-8")
        for item in connection.execute(
            "SELECT source_html_zlib FROM assessment_items WHERE case_id = ? ORDER BY item_order",
            (str(row["case_id"]),),
        )
    )
    text = layout_text(source_html)
    compact_source = compact_text(text)
    subject = str(row["subject"])
    subject_mentioned = compact_text(subject) in compact_source
    math_context = bool(MATH_CONTEXT_RE.search(text))
    support_marker_count = len({match.group(0) for match in SUPPORT_MARKER_RE.finditer(text)})
    result: list[TitleCandidate] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for label, raw_candidate, detection, line_number in candidate_rows(text):
        candidate = normalize_candidate(raw_candidate)
        key = compact_text(candidate)
        if (
            not candidate
            or key in seen
            or TABLE_HEADER_FRAGMENT_RE.fullmatch(candidate)
            or GENERIC_LABEL_VALUE_RE.fullmatch(candidate)
            or task_name_is_rejected(candidate)
        ):
            continue
        seen.add(key)
        nearby_source = "\n".join(lines[max(0, line_number - 2) : line_number + 15])
        alignment = standard_alignment(nearby_source, subject)
        other_subject_signal = bool(OTHER_SUBJECT_RE.search(nearby_source))
        name_label = explicit_name_label(label)
        complete = title_looks_complete(candidate)
        confidence, confidence_score = candidate_confidence(
            candidate=candidate,
            detection=detection,
            alignment=alignment,
            subject_mentioned=subject_mentioned,
            math_context=math_context,
            other_subject_signal=other_subject_signal,
            support_marker_count=support_marker_count,
            explicit_name_label=name_label,
            title_looks_complete=complete,
        )
        line_position = sum(len(value) + 1 for value in lines[:line_number])
        result.append(
            TitleCandidate(
                case_id=str(row["case_id"]),
                curriculum=str(row["curriculum"]),
                subject=subject,
                school_name=str(row["school_name"]),
                region=str(row["region"]),
                source_format=str(row["source_format"]),
                boundary_status=str(row["boundary_status"]),
                candidate=candidate,
                raw_candidate=raw_candidate,
                label=re.sub(r"\s+", " ", label).strip(),
                detection=detection,
                confidence=confidence,
                confidence_score=confidence_score,
                subject_alignment=alignment,
                subject_mentioned=subject_mentioned,
                math_context=math_context,
                other_subject_signal=other_subject_signal,
                support_marker_count=support_marker_count,
                explicit_name_label=name_label,
                title_looks_complete=complete,
                source_order=line_position,
                source_excerpt=source_excerpt(text, line_position),
            )
        )
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_unresolved_title_recovery_audit.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=root / "data" / "derived" / "math_assessment_unresolved_title_recovery_queue.csv",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        cases = unresolved_cases(connection)
        candidates = [candidate for row in cases for candidate in inspect_case(connection, row)]

    candidates.sort(
        key=lambda candidate: (
            {"high": 0, "review": 1, "reject": 2}[candidate.confidence],
            -candidate.confidence_score,
            candidate.case_id,
            candidate.source_order,
            candidate.candidate,
        )
    )
    counts = Counter(candidate.confidence for candidate in candidates)
    by_format = Counter(candidate.source_format for candidate in candidates)
    summary = {
        "schema_version": 1,
        "database": str(database),
        "unresolved_cases": len(cases),
        "candidate_count": len(candidates),
        "counts_by_confidence": dict(sorted(counts.items())),
        "candidates_by_source_format": dict(sorted(by_format.items())),
        "high_confidence_cases": len(
            {candidate.case_id for candidate in candidates if candidate.confidence == "high"}
        ),
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    args.json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(TitleCandidate.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(candidate) for candidate in candidates)
    print(
        json.dumps(
            {
                key: value
                for key, value in summary.items()
                if key != "candidates"
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
