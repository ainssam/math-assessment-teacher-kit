"""Propose conservative splits for hidden unbounded assessment bundles.

This pass is intentionally narrower than the general table parser.  It scans
only strong math-course boundaries, deduplicates identical source HTML inside
the same case, and accepts children only when an original ``평가영역명`` table
row, assessment structure, and direct course evidence agree.  It never mutates
the database or source documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_unresolved_math_assessment_titles import layout_text, standard_alignment
from audit_math_assessment_table_structure import SOURCE_HTML_MODULE, audit_html
from build_math_assessment_publish_db import task_name_is_rejected
from propose_math_assessment_explicit_item_recovery import (
    STRONG_BOUNDARIES,
    STRUCTURAL_DIRECT_VALUE_RE,
    source_course_identity_evidence,
    title_key,
)
from propose_math_assessment_table_boundary_repairs import split_candidates


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# These flags describe presentation complexity, not an ambiguous assessment
# boundary.  They may be recovered only after the generated child passes the
# browser renderer audit; every other table flag remains a hard rejection.
RECOVERABLE_PRESENTATION_FLAGS = frozenset(
    {
        "adjacent_compatible_table_fragments",
        "high_blank_cell_ratio",
        "large_table_without_header_signal",
        "section_local_trailing_blank_columns",
        "very_wide_table",
    }
)


def only_recoverable_presentation_flags(flags: object) -> bool:
    return set(str(value) for value in (flags or [])) <= RECOVERABLE_PRESENTATION_FLAGS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT
        / ".tmp"
        / "math_assessment_catalog_detail_explicit_recovery_precision_v3.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_unbounded_bundle_split_proposals.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "derived"
        / "math_assessment_unbounded_bundle_split_report.json",
    )
    return parser.parse_args()


def source_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    args = parse_args()
    database = args.database.resolve()
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    public_titles: defaultdict[str, set[str]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT case_id, title FROM assessment_items
        WHERE extraction_status = 'bounded'
          AND title_basis IN ('table', 'heading')
        """
    ):
        public_titles[str(row["case_id"])].add(title_key(str(row["title"])))

    rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.source_start, item.source_end, item.source_html_zlib,
               cases.curriculum, cases.subject, cases.school_name,
               cases.region, cases.district, status.source_format,
               status.boundary_status
        FROM assessment_items AS item
        JOIN cases USING (case_id)
        JOIN case_detail_status AS status USING (case_id)
        WHERE item.extraction_status = 'bundle_review'
          AND item.title_basis = 'unbounded_bundle'
          AND status.boundary_status IN (?, ?, ?)
        ORDER BY item.case_id, item.item_order
        """,
        tuple(sorted(STRONG_BOUNDARIES)),
    ).fetchall()
    connection.close()

    counts: Counter[str] = Counter()
    seen_case_sources: set[tuple[str, str]] = set()
    proposals: list[dict[str, object]] = []
    candidate_locations: defaultdict[tuple[str, str], list[tuple[int, int]]] = (
        defaultdict(list)
    )

    for row in rows:
        source_html = zlib.decompress(bytes(row["source_html_zlib"])).decode(
            "utf-8", errors="replace"
        )
        source_hash = source_sha256(source_html)
        case_id = str(row["case_id"])
        source_identity = (case_id, source_hash)
        if source_identity in seen_case_sources:
            counts["duplicate_case_source_skipped"] += 1
            continue
        seen_case_sources.add(source_identity)
        counts["unique_parents_scanned"] += 1

        candidates: list[dict[str, object]] = []
        for candidate in split_candidates(source_html):
            title = str(candidate.get("title") or "").strip()
            key = title_key(title)
            fragment = str(candidate.get("source_html") or "")
            alignment = standard_alignment(layout_text(fragment), str(row["subject"]))
            rubric_html = SOURCE_HTML_MODULE.rubric_tables_from_source_html(fragment)
            rubric_flags = list(audit_html(rubric_html)["flags"]) if rubric_html else []
            signals = dict(candidate.get("signals") or {})
            signals.update(
                {
                    "source_course_identity_evidence": source_course_identity_evidence(
                        alignment=alignment,
                        title=title,
                        subject=str(row["subject"]),
                    ),
                    "source_task_title": bool(
                        key
                        and not task_name_is_rejected(title)
                        and not STRUCTURAL_DIRECT_VALUE_RE.fullmatch(key)
                    ),
                    "not_already_public_by_title": key
                    not in public_titles[case_id],
                    # Presentation-only warnings may proceed to the renderer
                    # audit. Boundary, split-standard, duplicate-area and
                    # rowspan warnings still block a public child here.
                    "only_recoverable_table_flags": only_recoverable_presentation_flags(
                        candidate.get("flags")
                    ),
                    "only_recoverable_rubric_flags": only_recoverable_presentation_flags(
                        rubric_flags
                    ),
                }
            )
            accepted = bool(candidate.get("accepted")) and all(signals.values())
            record = {
                **candidate,
                "accepted": accepted,
                "signals": signals,
                "subject_alignment": alignment,
                "source_html_sha256": source_sha256(fragment),
                "rubric_table_structure_flags": rubric_flags,
                "rejection_reasons": [
                    name for name, passed in signals.items() if not passed
                ],
            }
            candidates.append(record)
            counts["candidates_total"] += 1
            counts["candidates_preduplicate_accepted"] += int(accepted)
            if accepted:
                candidate_locations[(case_id, key)].append(
                    (len(proposals), len(candidates) - 1)
                )

        if candidates:
            proposals.append(
                {
                    "item_id": str(row["item_id"]),
                    "case_id": case_id,
                    "item_order": int(row["item_order"]),
                    "curriculum": str(row["curriculum"]),
                    "subject": str(row["subject"]),
                    "school_name": str(row["school_name"]),
                    "region": str(row["region"]),
                    "district": str(row["district"]),
                    "source_format": str(row["source_format"]),
                    "boundary_status": str(row["boundary_status"]),
                    "parent_title": str(row["title"]),
                    "source_start": int(row["source_start"]),
                    "source_end": int(row["source_end"]),
                    "source_html_sha256": source_hash,
                    "candidates": candidates,
                }
            )

    # If two distinct parent fragments in one case propose the same title,
    # neither occurrence is chosen silently.
    for locations in candidate_locations.values():
        if len(locations) < 2:
            continue
        for proposal_index, candidate_index in locations:
            candidate = proposals[proposal_index]["candidates"][candidate_index]
            candidate["accepted"] = False
            candidate["signals"]["unique_title_within_batch"] = False
            candidate["rejection_reasons"].append("unique_title_within_batch")
            counts["batch_duplicate_candidates_rejected"] += 1

    output_rows: list[dict[str, object]] = []
    accepted_cases: set[str] = set()
    for proposal in proposals:
        candidates = proposal["candidates"]
        accepted = [candidate for candidate in candidates if candidate["accepted"]]
        if not accepted:
            continue
        for candidate in accepted:
            candidate["signals"].setdefault("unique_title_within_batch", True)
            counts[f"accepted_subject_{proposal['subject']}"] += 1
        counts["accepted_candidates"] += len(accepted)
        counts["accepted_parents"] += 1
        accepted_cases.add(str(proposal["case_id"]))
        output_rows.append(proposal)

    counts["accepted_cases"] = len(accepted_cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for proposal in output_rows:
            handle.write(
                json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    report = {
        "schema_version": 1,
        "database": str(database),
        "proposal_jsonl": str(args.output.resolve()),
        "counts": dict(sorted(counts.items())),
        "mutation_applied": False,
        "policy": (
            "Deduplicate identical case/source bundles, then accept only explicit "
            "source-table assessment-area titles with one assessment structure, "
            "direct course identity, no structural title, only recoverable "
            "presentation flags, and no public or batch duplicate. Every accepted "
            "child must subsequently pass the browser renderer audit."
        ),
    }
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
