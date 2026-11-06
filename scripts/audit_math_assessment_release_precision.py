"""Run source-traceability checks over every publicly served assessment item.

This audit is deliberately read-only.  It distinguishes release-blocking defects
from review signals so a broad heuristic warning is never treated as permission
to rewrite a school's assessment plan.
"""

from __future__ import annotations

import argparse
import csv
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

from lxml import html as lxml_html

from scripts.audit_math_assessment_detail_db import value_is_traceable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_STATUSES = ("bounded",)
PUBLIC_TITLE_BASES = ("table", "heading")
POLICY_TITLE_RE = re.compile(
    r"^(?:영역별|학기\s*단위\s*성취수준\s*설정|단원/?영역별\s*성취수준|"
    r"성취기준별\s*성취수준|평가\s*관련\s*제반\s*문제|평가요소\s*및\s*채점기준|"
    r"교수[·ㆍ]?학습\s*및\s*평가\s*계획)$"
)
DISAMBIGUATION_RE = re.compile(r"\s*\(\s*\d+\s*회\s*\)\s*$")
SCORE_RE = re.compile(r"\d{1,3}(?:\.\d+)?점")
WEIGHT_RE = re.compile(r"\d{1,3}(?:\.\d+)?%")
MONTH_TIMING = (
    r"(?:\d{1,2}월?\s*[~∼～\-]\s*\d{1,2}월|"
    r"\d{1,2}월(?:\s*\d{1,2}주)?(?:\s*[~∼～\-]\s*(?:\d{1,2}월\s*)?\d{1,2}주)?)"
)
TIMING_RE = re.compile(
    rf"(?:{MONTH_TIMING}(?:\s*,\s*{MONTH_TIMING})*"
    r"(?:\s*,\s*(?:\d{1,2}회|수시|상시)|\s*\(\s*\d{1,2}회\s*\))?"
    r"|\d{1,2}차시|수시|상시|학기\s*(?:중|말)|단원\s*(?:종료|말))"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data" / "publish" / "math_assessment_catalog_detail.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "derived" / "math_assessment_release_precision_audit.json",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=PROJECT_ROOT / "data" / "derived" / "math_assessment_release_precision_review_queue.csv",
    )
    return parser.parse_args()


def normalized_key(value: str) -> str:
    return re.sub(
        r"[^0-9A-Za-z가-힣ⅠⅡ]",
        "",
        unicodedata.normalize("NFKC", value or ""),
    ).lower()


def visible_text(value: str) -> str:
    root = lxml_html.fromstring(f"<main>{value}</main>")
    return " ".join(root.text_content().split())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sample(rows: list[dict[str, object]], value: dict[str, object], limit: int = 100) -> None:
    if len(rows) < limit:
        rows.append(value)


def main() -> None:
    args = parse_args()
    database_uri = f"file:{args.database.resolve().as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT item.item_id, item.case_id, item.item_order, item.title,
               item.title_basis, item.extraction_status, item.overview,
               item.method, item.timing, item.score, item.weight,
               item.source_html_zlib, item.rubric_html_zlib,
               item.source_html_char_count, item.rubric_html_char_count,
               cases.school_name, cases.curriculum, cases.subject,
               cases.region, cases.district
        FROM assessment_items AS item
        JOIN cases ON cases.case_id = item.case_id
        WHERE item.extraction_status = 'bounded'
          AND item.title_basis IN ('table', 'heading')
        ORDER BY item.case_id, item.item_order
        """
    ).fetchall()

    counts: Counter[str] = Counter()
    blocking_samples: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    review_rows: list[dict[str, object]] = []
    titles_by_case: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    payloads_by_case: defaultdict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    public_titles_by_case: defaultdict[str, list[str]] = defaultdict(list)

    for row in rows:
        counts["public_items"] += 1
        base = {
            "item_id": str(row["item_id"]),
            "case_id": str(row["case_id"]),
            "school_name": str(row["school_name"]),
            "curriculum": str(row["curriculum"]),
            "subject": str(row["subject"]),
            "region": str(row["region"]),
            "district": str(row["district"]),
            "title": str(row["title"]),
        }
        try:
            source_html = zlib.decompress(bytes(row["source_html_zlib"])).decode("utf-8")
            rubric_html = zlib.decompress(bytes(row["rubric_html_zlib"])).decode("utf-8")
            source_visible = visible_text(source_html)
            visible_text(rubric_html) if rubric_html.strip() else ""
        except (zlib.error, UnicodeDecodeError, ValueError) as error:
            counts["decode_or_parse_failures"] += 1
            sample(
                blocking_samples["decode_or_parse_failures"],
                {**base, "error": str(error)},
            )
            continue

        if len(source_html) != int(row["source_html_char_count"]):
            counts["source_length_mismatches"] += 1
            sample(blocking_samples["source_length_mismatches"], base)
        if len(rubric_html) != int(row["rubric_html_char_count"]):
            counts["rubric_length_mismatches"] += 1
            sample(blocking_samples["rubric_length_mismatches"], base)

        title = str(row["title"]).strip()
        title_core = DISAMBIGUATION_RE.sub("", title)
        title_in_source = bool(normalized_key(title_core)) and normalized_key(title_core) in normalized_key(source_visible)
        if not title_in_source:
            counts["titles_not_traceable_to_source"] += 1
            sample(blocking_samples["titles_not_traceable_to_source"], base)
        if POLICY_TITLE_RE.fullmatch(" ".join(title.split())):
            counts["public_policy_or_structure_titles"] += 1
            sample(blocking_samples["public_policy_or_structure_titles"], base)

        traceability_misses: list[str] = []
        for field in ("overview", "method", "timing", "score", "weight"):
            value = str(row[field] or "").strip()
            if value and not value_is_traceable(value, source_visible):
                traceability_misses.append(field)
        if traceability_misses:
            counts["items_with_derived_field_traceability_signal"] += 1
            review_rows.append({
                **base,
                "review_reason": "derived_field_not_exact_source_substring",
                "fields": "|".join(traceability_misses),
            })

        score = str(row["score"] or "").strip()
        weight = str(row["weight"] or "").strip()
        timing = str(row["timing"] or "").strip()
        method = str(row["method"] or "").strip()
        overview = str(row["overview"] or "").strip()
        if score and not SCORE_RE.fullmatch(score):
            counts["malformed_public_score_values"] += 1
            sample(blocking_samples["malformed_public_score_values"], {**base, "value": score})
        if weight and not WEIGHT_RE.fullmatch(weight):
            counts["malformed_public_weight_values"] += 1
            sample(blocking_samples["malformed_public_weight_values"], {**base, "value": weight})
        if timing and not TIMING_RE.fullmatch(timing):
            counts["malformed_public_timing_values"] += 1
            sample(blocking_samples["malformed_public_timing_values"], {**base, "value": timing})
        if method and re.search(r"gfedc|[□☑■þ]", method, re.I):
            counts["public_method_control_artifacts"] += 1
            sample(blocking_samples["public_method_control_artifacts"], {**base, "value": method})
        if len(overview) > 600:
            counts["public_overview_over_600_chars"] += 1
            sample(blocking_samples["public_overview_over_600_chars"], {**base, "value": overview[:700]})

        item_record = {**base, "item_order": int(row["item_order"])}
        title_key = normalized_key(title)
        titles_by_case[(str(row["case_id"]), title_key)].append(item_record)
        payload_hash = sha256_bytes(source_html.encode("utf-8"))
        payloads_by_case[(str(row["case_id"]), title_key, payload_hash)].append(item_record)
        public_titles_by_case[str(row["case_id"])].append(title)

    duplicate_title_groups = [value for value in titles_by_case.values() if len(value) > 1]
    duplicate_payload_groups = [value for value in payloads_by_case.values() if len(value) > 1]
    counts["duplicate_title_groups"] = len(duplicate_title_groups)
    counts["duplicate_title_items"] = sum(len(value) for value in duplicate_title_groups)
    counts["duplicate_exact_payload_groups"] = len(duplicate_payload_groups)
    counts["duplicate_exact_payload_items"] = sum(len(value) for value in duplicate_payload_groups)
    for group in duplicate_title_groups:
        for value in group:
            review_rows.append({
                **value,
                "review_reason": "duplicate_title_within_case",
                "fields": "",
            })
    for group in duplicate_payload_groups[:100]:
        sample(blocking_samples["duplicate_exact_payload_groups"], {"items": group})

    summary_mismatches: list[dict[str, object]] = []
    for row in connection.execute(
        """
        SELECT status.case_id, status.detected_title_count,
               status.detected_titles_json, cases.school_name, cases.subject
        FROM case_detail_status AS status
        JOIN cases ON cases.case_id = status.case_id
        WHERE status.extraction_status = 'bounded'
        ORDER BY status.case_id
        """
    ):
        expected = list(dict.fromkeys(public_titles_by_case.get(str(row["case_id"]), [])))
        try:
            detected = json.loads(str(row["detected_titles_json"]))
        except json.JSONDecodeError:
            detected = None
        if (
            not isinstance(detected, list)
            or int(row["detected_title_count"]) != len(expected)
            or [str(value) for value in detected] != expected
        ):
            counts["case_title_summary_mismatches"] += 1
            sample(summary_mismatches, {
                "case_id": str(row["case_id"]),
                "school_name": str(row["school_name"]),
                "subject": str(row["subject"]),
                "expected": expected,
                "detected": detected,
                "detected_title_count": int(row["detected_title_count"]),
            })
    connection.close()

    blocking_keys = (
        "decode_or_parse_failures",
        "source_length_mismatches",
        "rubric_length_mismatches",
        "titles_not_traceable_to_source",
        "public_policy_or_structure_titles",
        "duplicate_exact_payload_groups",
        "case_title_summary_mismatches",
        "malformed_public_score_values",
        "malformed_public_weight_values",
        "malformed_public_timing_values",
        "public_method_control_artifacts",
        "public_overview_over_600_chars",
    )
    gates = {f"zero_{key}": counts[key] == 0 for key in blocking_keys}
    gates["all_release_blockers_clear"] = all(gates.values())
    report = {
        "schema_version": 1,
        "database": str(args.database.resolve()),
        "scope": "Every bounded table/heading assessment item served by the public API",
        "counts": dict(sorted(counts.items())),
        "gates": gates,
        "blocking_samples": dict(sorted(blocking_samples.items())),
        "case_title_summary_mismatch_samples": summary_mismatches,
        "duplicate_title_group_samples": duplicate_title_groups[:100],
        "review_queue": str(args.queue.resolve()),
        "policy": (
            "Only exact source-traceability and internal consistency failures block release. "
            "Duplicate titles and derived-field substring misses remain teacher-review signals."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fieldnames = [
        "item_id", "case_id", "school_name", "curriculum", "subject", "region",
        "district", "title", "item_order", "review_reason", "fields",
    ]
    with args.queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_rows)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "counts": report["counts"],
        "gates": gates,
        "review_queue_rows": len(review_rows),
    }, ensure_ascii=False, indent=2))
    if not gates["all_release_blockers_clear"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
