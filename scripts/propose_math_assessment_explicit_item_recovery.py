"""Propose conservative recovery of explicit, source-bounded assessment items.

The current public catalogue intentionally hides every item inherited from an
ambiguous source bundle.  Some of those hidden items are nevertheless clean,
single-task tables with an explicit source label and matching achievement
standard.  This read-only pass identifies only that narrow subset.  It never
changes the source database or the original documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
import zlib
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_math_assessment_table_structure import (
    audit_html,
    restore_escaped_table_rows,
)
from scripts.audit_math_assessment_titles_full import audit_flags, confidence
from scripts.audit_unresolved_math_assessment_titles import (
    SUPPORT_MARKER_RE,
    candidate_rows,
    layout_text,
    normalize_candidate,
    standard_alignment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRONG_BOUNDARIES = {
    "subject_heading:assessment_anchor",
    "subject_heading_exact:assessment_anchor",
    "zip_member_subject:assessment_anchor",
}
BLOCKING_TABLE_FLAGS = {
    "excessive_table_count",
    "inconsistent_effective_columns",
    "invalid_span_value",
    "likely_unbounded_public_item",
    "multiple_assessment_area_labels",
    "multiple_course_code_prefixes",
    "multiple_distinct_assessment_areas",
    "multiple_performance_task_labels",
    "oversized_html",
    "rowspan_overflows_table",
    "whole_plan_policy_leak",
}
STRUCTURAL_DIRECT_VALUE_RE = re.compile(
    r"^(?:\(?\s*유형\s*\)?|명|영역만점|평가요소|평가항목|평가영역|"
    r"기본점수|\d+|별우선순위)$"
)
EXPLICIT_AREA_LABELS = {
    "과제명",
    "수행평가명",
    "수행평가영역",
    "수행평가영역명",
    "평가과제",
    "평가과제명",
    "평가명",
    "평가영역",
    "평가영역명",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "publish"
        / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_explicit_item_recovery_proposals.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_explicit_item_recovery_report.json",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="CURRICULUM|SUBJECT",
        help=(
            "Limit recovery to one curriculum-and-subject pair. Repeat for "
            "multiple pairs, for example --target '2015|수학Ⅱ'."
        ),
    )
    return parser.parse_args()


def title_key(value: str) -> str:
    return re.sub(
        r"[^0-9A-Za-z가-힣ⅠⅡ]",
        "",
        unicodedata.normalize("NFKC", value),
    )


def source_course_identity_evidence(
    *,
    alignment: str,
    title: str,
    subject: str,
) -> bool:
    """Require either the course code or its full source-authored name.

    A few plans state ``전 성취기준`` instead of printing each code. In that
    narrow case, a task title that literally contains the selected course name
    is still direct source evidence. Generic ``수학`` wording is intentionally
    excluded because it cannot distinguish courses.
    """

    if alignment == "expected":
        return True
    subject_key = title_key(subject)
    return bool(
        alignment == "unknown"
        and subject_key
        and subject_key != title_key("수학")
        and subject_key in title_key(title)
    )


def unique_direct_candidates(text: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for label, value, detection, line_number in candidate_rows(text):
        title = normalize_candidate(value)
        key = title_key(title)
        if not title or not key or key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "label": re.sub(r"\s+", " ", label).strip(),
                "title": title,
                "detection": detection,
                "line_number": line_number,
            }
        )
    return output


def label_key(value: str) -> str:
    return re.sub(r"\s+", "", value)


def competing_direct_candidates(
    current_title: str,
    candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return other candidates that could be a different assessment title.

    A source table commonly contains both an official ``평가영역명`` and a
    longer ``수행과제`` instruction.  They describe one assessment, not two.
    Conversely, when the current title came from ``수행과제``, a substantive
    explicit area name must win and the item stays in review.
    """

    current_key = title_key(current_title)
    matches = [
        candidate
        for candidate in candidates
        if title_key(str(candidate["title"])) == current_key
    ]
    if len(matches) != 1:
        return candidates
    current_label = label_key(str(matches[0]["label"]))
    output: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate is matches[0]:
            continue
        other_label = label_key(str(candidate["label"]))
        other_value = label_key(str(candidate["title"]))
        if current_label in EXPLICIT_AREA_LABELS and other_label.startswith("수행과제"):
            continue
        # Some plans put a structural placeholder such as ``별 우선순위`` in
        # a second area-labelled cell.  It is not a competing assessment
        # title, even though it shares the surrounding table label.
        if (
            current_label in EXPLICIT_AREA_LABELS
            and other_label in EXPLICIT_AREA_LABELS
            and STRUCTURAL_DIRECT_VALUE_RE.fullmatch(other_value)
        ):
            continue
        if (
            current_label.startswith("수행과제")
            and other_label in EXPLICIT_AREA_LABELS
            and STRUCTURAL_DIRECT_VALUE_RE.fullmatch(other_value)
        ):
            continue
        output.append(candidate)
    return output


def target_pairs(values: list[str]) -> set[tuple[str, str]]:
    """Parse repeatable curriculum|subject filters without widening scope."""

    output: set[tuple[str, str]] = set()
    for raw in values:
        curriculum, separator, subject = str(raw).partition("|")
        curriculum = curriculum.strip()
        subject = subject.strip()
        if not separator or not curriculum or not subject:
            raise ValueError(
                "--target must be formatted as CURRICULUM|SUBJECT, "
                f"received: {raw!r}"
            )
        output.add((curriculum, subject))
    return output


def main() -> None:
    args = parse_args()
    database = args.database.resolve()
    targets = target_pairs(args.target)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    target_clause = ""
    target_params: list[str] = []
    if targets:
        target_clause = " AND (" + " OR ".join(
            "(cases.curriculum = ? AND cases.subject = ?)" for _ in targets
        ) + ")"
        for curriculum, subject in sorted(targets):
            target_params.extend((curriculum, subject))
    rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.title_raw, item.title_basis, item.extraction_status,
               item.source_html_zlib, item.source_html_char_count,
               cases.curriculum, cases.subject, cases.school_name,
               cases.region, cases.district,
               status.source_format, status.boundary_status
        FROM assessment_items AS item
        JOIN cases USING (case_id)
        JOIN case_detail_status AS status USING (case_id)
        WHERE item.extraction_status = 'bundle_review'
          AND item.title_basis = 'table'
          AND status.boundary_status IN (?, ?, ?)
        """
        + target_clause
        +
        """
        ORDER BY item.case_id, item.item_order
        """,
        tuple(sorted(STRONG_BOUNDARIES)) + tuple(target_params),
    ).fetchall()

    public_titles: defaultdict[str, set[str]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT case_id, title
        FROM assessment_items
        WHERE extraction_status = 'bounded'
          AND title_basis IN ('table', 'heading')
        """
    ):
        public_titles[str(row["case_id"])].add(title_key(str(row["title"])))
    connection.close()

    proposals: list[dict[str, object]] = []
    duplicate_groups: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for row in rows:
        source_html = restore_escaped_table_rows(
            zlib.decompress(bytes(row["source_html_zlib"])).decode(
                "utf-8", errors="replace"
            )
        )
        text = layout_text(source_html)
        direct = unique_direct_candidates(text)
        key = title_key(str(row["title"]))
        exact_matches = [candidate for candidate in direct if title_key(str(candidate["title"])) == key]
        competing = competing_direct_candidates(str(row["title"]), direct)
        flags = audit_flags(str(row["title"]), str(row["title_basis"]))
        title_confidence = confidence(
            flags,
            str(row["title_basis"]),
            explicit_source_label=True,
        )
        alignment = standard_alignment(text, str(row["subject"]))
        support_marker_count = len(
            {match.group(0) for match in SUPPORT_MARKER_RE.finditer(text)}
        )
        table_audit = audit_html(source_html)
        table_flags = set(str(flag) for flag in table_audit["flags"])
        signals = {
            "strong_subject_boundary": str(row["boundary_status"])
            in STRONG_BOUNDARIES,
            "table_title_basis": str(row["title_basis"]) == "table",
            "title_traceable": bool(key and key in title_key(text)),
            "single_direct_title": not competing,
            "exact_direct_title_match": len(exact_matches) == 1,
            "direct_table_row": bool(
                exact_matches and exact_matches[0]["detection"] == "table_row"
            ),
            "source_course_identity_evidence": source_course_identity_evidence(
                alignment=alignment,
                title=str(row["title"]),
                subject=str(row["subject"]),
            ),
            "assessment_support_markers": support_marker_count >= 2,
            "title_not_rejected": title_confidence != "reject",
            "single_assessment_structure": not bool(
                table_flags.intersection(BLOCKING_TABLE_FLAGS)
            ),
            "not_already_public_by_title": key
            not in public_titles[str(row["case_id"])],
        }
        rejection_reasons = [name for name, passed in signals.items() if not passed]
        proposal = {
            "item_id": str(row["item_id"]),
            "case_id": str(row["case_id"]),
            "item_order": int(row["item_order"]),
            "curriculum": str(row["curriculum"]),
            "subject": str(row["subject"]),
            "school_name": str(row["school_name"]),
            "region": str(row["region"]),
            "district": str(row["district"]),
            "source_format": str(row["source_format"]),
            "boundary_status": str(row["boundary_status"]),
            "title": str(row["title"]),
            "title_raw": str(row["title_raw"]),
            "title_basis": str(row["title_basis"]),
            "source_html_sha256": hashlib.sha256(
                source_html.encode("utf-8")
            ).hexdigest(),
            "source_html_char_count": len(source_html),
            "direct_title_candidates": direct,
            "competing_direct_title_candidates": competing,
            "subject_alignment": alignment,
            "support_marker_count": support_marker_count,
            "title_confidence": title_confidence,
            "title_audit_flags": flags,
            "table_audit_flags": sorted(table_flags),
            "signals": signals,
            "rejection_reasons": rejection_reasons,
            "decision": "accepted" if not rejection_reasons else "rejected",
        }
        proposals.append(proposal)
        if not rejection_reasons:
            duplicate_groups[(str(row["case_id"]), key)].append(len(proposals) - 1)

    # A repeated title in the same source case can represent a duplicated page,
    # semester copy, or parser overlap.  It requires a separate boundary review;
    # never choose one occurrence silently.
    for indexes in duplicate_groups.values():
        if len(indexes) < 2:
            continue
        for index in indexes:
            proposal = proposals[index]
            signals = proposal["signals"]
            assert isinstance(signals, dict)
            signals["unique_title_within_recovery_batch"] = False
            reasons = proposal["rejection_reasons"]
            assert isinstance(reasons, list)
            reasons.append("duplicate_title_within_recovery_batch")
            proposal["decision"] = "rejected"
    for proposal in proposals:
        signals = proposal["signals"]
        assert isinstance(signals, dict)
        signals.setdefault("unique_title_within_recovery_batch", True)

    counts: Counter[str] = Counter()
    for proposal in proposals:
        decision = str(proposal["decision"])
        counts[f"decision_{decision}"] += 1
        counts[f"source_format_{proposal['source_format']}"] += 1
        if decision == "accepted":
            counts[f"accepted_subject_{proposal['subject']}"] += 1
        for reason in proposal["rejection_reasons"]:
            counts[f"rejected_{reason}"] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(
                json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    report = {
        "schema_version": 1,
        "database": str(database),
        "proposal_jsonl": str(args.output.resolve()),
        "target_items": len(proposals),
        "targets": [
            {"curriculum": curriculum, "subject": subject}
            for curriculum, subject in sorted(targets)
        ],
        "accepted_items": counts["decision_accepted"],
        "accepted_cases": len(
            {
                str(row["case_id"])
                for row in proposals
                if row["decision"] == "accepted"
            }
        ),
        "counts": dict(sorted(counts.items())),
        "mutation_applied": False,
        "policy": (
            "Accept only one direct source-table task title with an exact title "
            "match, course identity proven by an expected achievement-standard "
            "prefix or the full non-generic course name in that source-authored "
            "title, at least two assessment-structure markers, no unbounded/"
            "multi-task table signal, and no public or batch duplicate title."
        ),
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
