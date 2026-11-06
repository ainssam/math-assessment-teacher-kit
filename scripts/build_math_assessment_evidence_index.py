"""Create a privacy-conscious, model-ready evidence index from math plans.

The source JSONL retains full extraction text locally.  The evidence index keeps
only bounded assessment-plan passages and deterministic signals so model review
can compare plans without sending whole multi-subject documents.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import tempfile
from pathlib import Path

from math_subject_aliases import SUBJECT_PATTERNS, subject_hits as detect_subject_hits


ASSESSMENT_ANCHORS = re.compile(
    r"수행\s*평가|평가\s*(?:계획|방법|기준|요소|영역)|채점\s*기준|"
    r"성취\s*기준|반영\s*비율|배점|루브릭",
    re.IGNORECASE,
)
ACTION_TAGS: dict[str, re.Pattern[str]] = {
    "탐구": re.compile(r"탐구(?:\s*(?:보고서|활동|과제))?"),
    "프로젝트": re.compile(r"프로젝트"),
    "문제해결": re.compile(r"문제\s*해결"),
    "수학적모델링": re.compile(r"(?:수학적\s*)?모델링"),
    "발표": re.compile(r"발표"),
    "토론": re.compile(r"토론"),
    "포트폴리오": re.compile(r"포트폴리오"),
    "보고서": re.compile(r"보고서"),
    "제작": re.compile(r"제작"),
    "실험": re.compile(r"실험"),
}
TASK_CONTEXT = re.compile(
    r"수행\s*평가|평가\s*(?:영역|과제|내용|방법)|영역\s*명|과제\s*명|활동\s*명|채점\s*기준",
    re.IGNORECASE,
)
SELECTED_BOXES = {"■", "☑", "☒", "✓", "✔"}
UNSELECTED_BOXES = {"□", "☐"}
COURSE_HEADER = re.compile(
    r"(?im)^(?:#{1,6}\s*)?\d{4}\s*학년도[^\n]{0,180}"
    r"(?:교수\s*[·ㆍ‧/\-]?\s*학습|교수학습)[^\n]{0,100}평가\s*계획[^\n]*$"
)
TASK_SECTION_HEADER = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:[가-힣0-9]+[.)]?\s*)?수행\s*평가\s*"
    r"(?:세부\s*)?(?:계획|기준|내용|방법|채점)[^\n]*$"
)
ASSESSMENT_TABLE_HEADER = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:[가-힣0-9]+[.)]?\s*)?평가\s*영역\s*및\s*반영\s*비율[^\n]*$"
)
NEXT_NON_TASK_SECTION = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:\d+|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)[.)]\s*"
    r"(?:결시|학적|평가\s*결과|성적|최소\s*성취|기타)[^\n]*$"
)
TASK_ITEM_HEADING = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?[가-하][.)]\s*([^\n<]{2,100})\s*$")


def mask_sensitive(text: str) -> str:
    """Remove common contact/identity strings from model-ready excerpts."""
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[이메일]", text)
    text = re.sub(r"(?<!\d)01[0-9][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)", "[전화번호]", text)
    text = re.sub(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)", "[식별번호]", text)
    return text


def detected_action_tags(text: str, *, assume_task_context: bool = False) -> list[str]:
    """Return action tags supported by task context or a selected checkbox.

    Korean evaluation templates often print every available method next to an
    empty box.  Counting raw word occurrences would therefore turn
    ``□ 프로젝트`` into a false project-assessment signal.
    """
    detected: list[str] = []
    for name, pattern in ACTION_TAGS.items():
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            before_on_line = text[line_start:match.start()]
            boxes = re.findall(r"[■☑☒✓✔□☐]", before_on_line)
            if boxes:
                if boxes[-1] in SELECTED_BOXES:
                    detected.append(name)
                    break
                if boxes[-1] in UNSELECTED_BOXES:
                    continue
            context = text[max(0, match.start() - 320):min(len(text), match.end() + 320)]
            if assume_task_context or TASK_CONTEXT.search(context):
                detected.append(name)
                break
    return detected


def performance_task_text(text: str) -> tuple[str, str]:
    detail = TASK_SECTION_HEADER.search(text)
    if detail:
        tail = text[detail.start():]
        next_section = NEXT_NON_TASK_SECTION.search(tail, max(1, detail.end() - detail.start()))
        return tail[:next_section.start()] if next_section else tail, "performance_detail_heading"
    table = ASSESSMENT_TABLE_HEADER.search(text)
    if table:
        return text[table.start():], "assessment_table_heading"
    return text, "full_subject_section"


def task_name_candidates(text: str) -> list[str]:
    names: list[str] = []
    for match in TASK_ITEM_HEADING.finditer(text):
        name = re.sub(r"\s+", " ", match.group(1)).strip(" -*#")
        if re.search(r"결시|학적|처리|성취\s*수준|평가\s*결과|유의\s*사항", name):
            continue
        if name and name not in names:
            names.append(name)
    return names[:12]


def merged_windows(text: str, positions: list[int], radius: int = 700, cap: int = 12_000) -> str:
    intervals: list[tuple[int, int]] = []
    for position in positions:
        start, end = max(0, position - radius), min(len(text), position + radius)
        if intervals and start <= intervals[-1][1] + 80:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    parts: list[str] = []
    used = 0
    for start, end in intervals:
        piece = text[start:end].strip()
        if not piece:
            continue
        remaining = cap - used
        if remaining <= 0:
            break
        parts.append(piece[:remaining])
        used += min(len(piece), remaining)
    return "\n\n[...문맥 전환...]\n\n".join(parts)


def pattern_for(subject: str) -> str | None:
    for _, known_subject, pattern in SUBJECT_PATTERNS:
        if known_subject == subject:
            return pattern
    return None


def subject_position(text: str, subject: str) -> int | None:
    """Prefer a subject occurrence that is nearest to assessment-plan content."""
    pattern = pattern_for(subject)
    if not pattern:
        return None
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    if not matches:
        return None
    anchors = [match.start() for match in ASSESSMENT_ANCHORS.finditer(text)]
    def proximity(match: re.Match[str]) -> tuple[int, int, int]:
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        explicit_label = bool(re.match(r"\s*#{1,6}\s*", line) or re.search(r"과목\s*명?|교과\s*목?", line))
        nearby = sum(abs(anchor - match.start()) <= 4500 for anchor in anchors)
        return int(explicit_label), nearby, -match.start()
    return max(matches, key=proximity).start()


def subject_section(text: str, position: int) -> tuple[int, int, str]:
    """Bound evidence to one course section when a combined plan has headers."""
    headers = [match.start() for match in COURSE_HEADER.finditer(text)]
    previous = max((value for value in headers if value <= position), default=None)
    following = min((value for value in headers if value > position), default=None)
    if previous is not None and position - previous <= 250_000:
        end = following if following is not None else len(text)
        if end - previous <= 300_000:
            return previous, end, "course_header"
    return max(0, position - 3500), min(len(text), position + 12_000), "bounded_window"


def selected_anchor_positions(text: str, subject_position_local: int) -> list[int]:
    groups = (
        re.compile(r"수행\s*평가", re.IGNORECASE),
        re.compile(r"평가\s*영역|영역\s*명|과제\s*명|활동\s*명", re.IGNORECASE),
        re.compile(r"평가\s*기준|채점\s*기준|루브릭", re.IGNORECASE),
        re.compile(r"반영\s*비율|배점", re.IGNORECASE),
        re.compile(r"성취\s*기준", re.IGNORECASE),
        re.compile(r"평가\s*방법|평가\s*요소", re.IGNORECASE),
    )
    positions = {subject_position_local}
    for pattern in groups:
        matches = [match.start() for match in pattern.finditer(text)]
        if len(matches) <= 6:
            positions.update(matches)
        elif matches:
            indexes = {0, 1, len(matches) // 3, len(matches) // 2, (len(matches) * 2) // 3, len(matches) - 1}
            positions.update(matches[index] for index in indexes)
    return sorted(positions)


def evidence_records(record: dict[str, object]) -> list[dict[str, object]]:
    text = mask_sensitive(str(record.get("text") or ""))
    # Re-run subject detection from the preserved full text so improvements to
    # the alias rules apply to every batch, including batches extracted before
    # the current rules were added.  Fall back to stored labels only when text
    # extraction produced no usable subject label.
    labels = detect_subject_hits(text) if text else []
    if not labels:
        labels = record.get("subject_hits") or []
    results: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for label in labels:
        if not isinstance(label, dict):
            continue
        subject = str(label.get("subject") or "")
        curriculum = str(label.get("curriculum_hint") or "")
        identity = (curriculum, subject)
        if not subject or identity in seen:
            continue
        seen.add(identity)
        position = subject_position(text, subject)
        if position is None:
            continue
        start, end, boundary_method = subject_section(text, position)
        local = text[start:end]
        task_local, task_boundary_method = performance_task_text(local)
        task_names = task_name_candidates(task_local)
        anchor_positions = selected_anchor_positions(local, position - start)
        snippets = merged_windows(local, anchor_positions, radius=650, cap=12000)
        action_tags = detected_action_tags(task_local, assume_task_context=task_boundary_method != "full_subject_section")
        marker_counts = {
            "performance_assessment": len(re.findall(r"수행\s*평가", local)),
            "rubric": len(re.findall(r"평가\s*기준|채점\s*기준|루브릭", local)),
            "achievement_standard": len(re.findall(r"성취\s*기준", local)),
            "weight_or_points": len(re.findall(r"반영\s*비율|배점", local)),
            "assessment_method": len(re.findall(r"평가\s*방법|평가\s*요소", local)),
        }
        score = (
            min(marker_counts["performance_assessment"], 3) * 3
            + min(marker_counts["rubric"], 3) * 2
            + min(marker_counts["achievement_standard"], 3) * 2
            + min(marker_counts["weight_or_points"], 2)
            + min(marker_counts["assessment_method"], 2) * 2
            + min(len(action_tags), 5)
        )
        if record.get("extract_status") != "ok":
            score -= 8
        source = record.get("source") or {}
        results.append({
            "source": source,
            "sha256": record.get("sha256", ""),
            "extract_status": record.get("extract_status"),
            "char_count": record.get("char_count", 0),
            "section_char_count": len(local),
            "section_boundary_method": boundary_method,
            "task_section_char_count": len(task_local),
            "task_section_boundary_method": task_boundary_method,
            "task_name_candidates": task_names,
            "curriculum_hint": curriculum,
            "subject": subject,
            "curriculum_code_hints": record.get("curriculum_code_hints") or [],
            "marker_counts": marker_counts,
            "action_tags": action_tags,
            "evidence_score": score,
            "evidence_text": snippets,
        })
    return results


def _legacy_evidence_record(record: dict[str, object]) -> dict[str, object]:
    """Compatibility shim for readers that imported the earlier helper."""
    records = evidence_records(record)
    return records[0] if records else {
        "source": record.get("source") or {}, "extract_status": record.get("extract_status"),
        "evidence_score": -8, "evidence_text": "", "action_tags": [], "marker_counts": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="nonzero for a bounded test run")
    parser.add_argument("--output-prefix", default="math_assessment_evidence")
    parser.add_argument("--input-jsonl", type=Path, action="append", default=[], help="explicit source batch; repeatable")
    parser.add_argument("--replacement-jsonl", type=Path, action="append", default=[], help="retry rows that replace weaker initial extraction; repeatable")
    args = parser.parse_args()

    derived = args.derived_dir
    inputs = [str(path) for path in args.input_jsonl]
    if not inputs:
        inputs = sorted(glob.glob(str(derived / "math_subject_candidate_text_[0-9]*.jsonl")))
        inputs += sorted(glob.glob(str(derived / "math_allplan_remaining_text_[0-9]*.jsonl")))
    if not inputs:
        raise SystemExit("no candidate text batches found")
    full_output = derived / f"{args.output_prefix}_source.jsonl"
    evidence_output = derived / f"{args.output_prefix}_index.jsonl"
    summary_output = derived / f"{args.output_prefix}_summary.json"
    for target in (full_output, evidence_output, summary_output):
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing output: {target}")

    temp_paths: list[Path] = []
    files = []
    status = collections.Counter()
    curricula = collections.Counter()
    subjects = collections.Counter()
    actions = collections.Counter()
    status_rank = {"ok": 4, "short": 3, "failed": 2, "missing": 1}
    replacements: dict[str, dict[str, object]] = {}
    replacement_bad = 0
    for replacement_path in args.replacement_jsonl:
        with replacement_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    replacement_bad += 1
                    continue
                source = candidate.get("source") or {}
                source_id = str(source.get("saved_path") or source.get("final_url") or "")
                current = replacements.get(source_id)
                if source_id and (
                    current is None
                    or (
                        status_rank.get(str(candidate.get("extract_status") or ""), 0),
                        int(candidate.get("char_count") or 0),
                    ) > (
                        status_rank.get(str(current.get("extract_status") or ""), 0),
                        int(current.get("char_count") or 0),
                    )
                ):
                    replacements[source_id] = candidate

    total = evidence_rows = bad = duplicate_sources = replacements_used = 0
    seen_sources: set[str] = set()
    try:
        for target in (full_output, evidence_output):
            fd, name = tempfile.mkstemp(prefix=f"{args.output_prefix}_", suffix=".partial", dir=derived)
            os.close(fd)
            temp_paths.append(Path(name))
        with temp_paths[0].open("w", encoding="utf-8", newline="\n") as raw_out, temp_paths[1].open("w", encoding="utf-8", newline="\n") as evidence_out:
            for input_name in inputs:
                count = 0
                with Path(input_name).open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            bad += 1
                            continue
                        source = record.get("source") or {}
                        source_id = str(source.get("saved_path") or source.get("final_url") or "")
                        if source_id in seen_sources:
                            duplicate_sources += 1
                            continue
                        if source_id:
                            seen_sources.add(source_id)
                        replacement = replacements.get(source_id)
                        if replacement is not None and (
                            status_rank.get(str(replacement.get("extract_status") or ""), 0),
                            int(replacement.get("char_count") or 0),
                        ) > (
                            status_rank.get(str(record.get("extract_status") or ""), 0),
                            int(record.get("char_count") or 0),
                        ):
                            record = replacement
                            replacements_used += 1
                        total += 1
                        count += 1
                        raw_out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                        for evidence in evidence_records(record):
                            evidence_rows += 1
                            evidence_out.write(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")) + "\n")
                            status[str(evidence["extract_status"])] += 1
                            for value in evidence["curriculum_code_hints"]:
                                curricula[str(value)] += 1
                            subjects[str(evidence["subject"])] += 1
                            for action in evidence["action_tags"]:
                                actions[action] += 1
                        if args.limit and total >= args.limit:
                            break
                files.append({"name": Path(input_name).name, "rows": count})
                if args.limit and total >= args.limit:
                    break
        os.replace(temp_paths[0], full_output)
        os.replace(temp_paths[1], evidence_output)
        temp_paths.clear()
        summary = {
            "input_files": files,
            "total_source_rows": total,
            "total_subject_evidence_rows": evidence_rows,
            "bad_json_rows": bad,
            "duplicate_source_rows_skipped": duplicate_sources,
            "replacement_rows_loaded": len(replacements),
            "replacement_rows_used": replacements_used,
            "replacement_bad_json_rows": replacement_bad,
            "extract_status": dict(status),
            "curriculum_code_hints": dict(curricula),
            "subject_label_counts": dict(subjects),
            "action_tag_counts": dict(actions),
            "evidence_text_limit": 12000,
            "privacy_masking": ["email", "mobile_phone", "resident_identifier"],
        }
        fd, name = tempfile.mkstemp(prefix=f"{args.output_prefix}_", suffix=".partial", dir=derived)
        os.close(fd)
        summary_temp = Path(name)
        with summary_temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(summary_temp, summary_output)
        print(json.dumps({"source": str(full_output), "evidence": str(evidence_output), "summary": str(summary_output), "total_source_rows": total, "total_subject_evidence_rows": evidence_rows, "bad_json_rows": bad}, ensure_ascii=False))
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
