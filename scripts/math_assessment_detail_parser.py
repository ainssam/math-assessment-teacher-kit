"""Loss-minimising parser for one math subject's performance-assessment section.

The public catalogue used to collapse one source document and subject into a
single summary row.  This module keeps the source wording and table structure,
then identifies individual assessment headings only when the document itself
provides a usable boundary.  It never invents a task title.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from html.parser import HTMLParser as StdlibHTMLParser
from pathlib import Path

from scripts.build_math_assessment_publish_db import html_tables

CONTEXT_JUMP_MARKERS = ("[...문맥 전환...]", "[…문맥 전환…]")
COURSE_HEADING_MARKERS = (
    "교수학습및평가운영계획",
    "교수·학습및평가운영계획",
    "교수학습및평가계획",
    "교수·학습및평가계획",
    "교수학습및평가계획서",
    "교수·학습및평가계획서",
    "교수학습-평가방법",
    "교수학습및평가방법",
)
ZIP_MEMBER_RE = re.compile(r"^\[zip:(?P<name>.+?)\]\[(?P<status>[^\]]+)\]\s*$", re.I)
MAX_BOUNDED_ITEMS = 12
PIPE_SEPARATOR_RE = re.compile(r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*")
BLOCK_END_RE = re.compile(
    r"(?:결시자|미응시자|학적\s*변동|성적\s*처리|이의\s*신청|평가\s*결과의\s*활용|"
    r"교수\s*학습\s*운영\s*계획|성취도|성취기준별\s*성취수준|재응시|결과물\s*보존)"
)
ITEM_PREFIX_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"(?P<letter>[가-하])\s*[.)]|"
    r"(?P<number>\d{1,2})\s*[.)]|"
    r"\((?P<paren>\d{1,2})\)|"
    r"(?P<circled>[①-⑳])"
    r")\s*(?P<title>.+?)\s*$"
)
ASSESSMENT_MARKER_RE = re.compile(
    r"성취기준|평가\s*개요|평가\s*방법|채점\s*기준|세부\s*기준|세부\s*평가\s*척도|"
    r"반영\s*비율|점수\s*/?\s*반영|평가\s*요소|배점|만점|실시\s*시기"
)
PERFORMANCE_MARKER_RE = re.compile(
    r"평가\s*개요|평가\s*방법|채점\s*기준|세부\s*기준|세부\s*평가\s*척도|"
    r"반영\s*비율|점수\s*/?\s*반영|평가\s*요소|배점|만점|실시\s*시기"
)
GENERIC_TITLE_RE = re.compile(
    r"^(?:수행평가|정기시험|평가\s*세부\s*계획|평가의?\s*(?:목적|방침|방향)|"
    r"성취기준(?:과\s*성취수준)?|채점\s*기준|평가\s*방법|성취도|"
    r"결시자.*|미응시자.*|학적\s*변동.*|성적\s*처리.*|평가\s*결과.*)$"
)
EXPLICIT_TITLE_LABEL_RE = re.compile(
    r"^(?:평가영역(?:명|[1-9])?|수행평가(?:명|영역|과제명)|수행과제(?:명)?|평가과제명|과제명)$"
)
TITLE_VALUE_STOP_LABELS = {
    "영역만점",
    "만점",
    "총점",
    "학기",
    "반영비율",
    "평가시기",
    "평가방법",
    "평가단원",
    "성취기준",
    "평가요소",
    "채점기준",
    "기본점수",
}
TITLE_VALUE_STOP_LABEL_RE = re.compile(
    r"^(?:영역?만점(?:점)?|총점|학기|반영비율|평가시기(?:횟수)?|평가방법\d*|"
    r"평가단원|관련?성취기준|교육과정성취기준|"
    r"평가요소(?:배점|채점요소)?|채점기준|세부기준|기본점수|배점|"
    r"평가항목|평가내용(?:점수|및요소|평가방법)?|평가방식|평가만점|"
    r"성취수준|처리기준|동점자처리기준순위|평가수준채점기준|"
    r"점수부여기준|기준영역|구분|시기)$"
)
NON_TASK_TITLE_RE = re.compile(
    r"^(?:(?:제?[12]|중간|기말)\s*(?:차|회)?\s*(?:정기)?\s*(?:고사|시험)|"
    r"[12]\s*(?:차|회)|정기\s*(?:고사|시험)(?:\s*\(\s*\d+%\s*\))?|"
    r"선택형|서[·‧ㆍ]?논술형)$"
)
STRUCTURAL_HEADING_RE = re.compile(
    r"^(?:평가\s*개요(?:표)?|채점\s*기준표?|공통\s*(?:사항|유의\s*사항)|개요|영역|"
    r"세부\s*내용\s*및\s*평가\s*척도표|세부\s*(?:채점\s*)?기준|피드백\s*및\s*기록|"
    r"(?:수행)?평가\s*(?:세부\s*)?(?:계획|기준|기준안|운영)|"
    r"수행\s*평가\s*세부\s*기준\s*\([^)]*\)|"
    r"수행평가\s*(?:개요|분할\s*점수(?:\s*산출)?|성취율과\s*원점수)|"
    r"(?:수행)?평가\s*영역\s*및\s*(?:평가\s*기준|반영\s*비율)|"
    r"수행평가\s*영역\s*및\s*배점|"
    r"수행평가\s*영역별\s*(?:평가\s*요소\s*및\s*채점\s*기준|성취기준\s*및\s*평가\s*척도)|"
    r"(?:평가\s*)?영역별\s*(?:세부\s*)?(?:평가\s*)?(?:기준|채점\s*기준|반영\s*비율)|"
    r"영역별\s*평가\s*방법과\s*채점\s*기준|평가\s*영역\s*및\s*배점|"
    r"세부\s*(?:시행\s*)?계획|"
    r"평가\s*(?:요소\s*및\s*(?:채점\s*기준|배점|성취\s*기준)|항목과\s*배점|과제)|"
    r"평가\s*방법\s*및\s*내용|"
    r"(?:관련\s*)?성취기준|성취\s*기준과\s*평가\s*기준|"
    r"성취기준\s*및\s*(?:평가기준|성취수준|평가\s*방법)|"
    r"교육과정\s*성취기준\s*및\s*평가\s*기준(?:,\s*평가\s*요소\s*및\s*배점)?|"
    r"\[?\s*(?:평가\s*)?유의\s*사항\s*\]?|출제\s*계획표?|학기\s*단위\s*성취수준|최소\s*성취수준\s*진술문|"
    r"결시생?\s*처리기준|동점자\s*처리\s*기준|"
    r"(?:사회정서학습\s*연계\s*)?정의적\s*(?:능력|영역)\s*평가(?:의\s*실제|\s*(?:방안|계획|세부\s*사항|요소와\s*평가\s*방법))?|"
    r"(?:수학\s*)?학습\s*과정\s*평가|서(?:술)?[·‧ㆍ]?\s*논술형\s*평가(?:\s*계획)?|세부\s*평가\s*척도|"
    r"평가\s*방법\s*및\s*결과의\s*활용|정기시험\s*및\s*수행평가\s*세부계획|"
    r"기타\s*사항|(?:평가과제|수행과제|평가영역|수행)\s*[12]|"
    r"평가의?\s*종류와\s*반영\s*비율|시행\s*계획|영역별\s*세부\s*계획|"
    r"수행평가\s*성취기준)$"
)
STRUCTURAL_EXACT_COMPACT = {
    "항목별계획",
    "평가영역",
    "평가요소별세부채점기준",
    "평가항목별채점기준",
    "기본점수부여여부및방법",
    "평가방법및활용",
    "고사별배점",
    "수행평가의세부기준평가과제별로작성",
    "수행평가세부기준및배점",
    "수행평가세부계획",
    "수업참여도세부기준",
    "방침",
    "수행평가과제별개요",
    "수행평가범위와기준",
    "평가과제별세부계획",
    "AI활용금지범위",
    "수행평가인정점산출기준",
    "수행평가평가기준",
    "과정중심수행평가세부계획",
    "평가방법및반영비율",
    "수업계획",
    "수행평가영역및평가항목배점및채점기준",
    "수행평가요소및성취기준",
    "평가과제별반영비율및성취수준",
    "평가과제별채점기준",
    "수행평가1",
    "수행평가2",
    "세부평가내용",
    "평가방법및평가내용",
    "정기시험세부계획",
    "과제별배점",
    "최종배점",
    "수행평가내용및평가세부기준",
    "수행평가인정점부여기준",
    "수행평가세부기준영역별배점및채점기준",
    "수행평가세부계획과목특성에따라양식변경",
    "기본방향",
    "평가방법과반영비율",
    "수행평가세부계획교과사정에따라변경될수있음",
    "수행평가세부계획1",
    "수행평가세부계획2",
    "수행평가세부계획평가과제별로작성",
    "항목별평가기준",
    "항목별",
    "영역별세부",
    "영역별",
    "일반사항",
    "학기단위성취수준설정",
    "최소성취수준설정",
    "최소성취수준설정공통과목",
    "1학기",
    "2학기",
    "성취기준과",
    "통계",
    "벡터",
    "행렬",
}
EXPECTED_STANDARD_PREFIXES = {
    "수학": ("10수학",),
    "공통수학1": ("10공수1",),
    "공통수학2": ("10공수2",),
    "기본수학1": ("10기수1",),
    "기본수학2": ("10기수2",),
    "대수": ("12대수",),
    "미적분Ⅰ": ("12미적Ⅰ", "12미적I"),
    "미적분Ⅱ": ("12미적Ⅱ", "12미적II"),
    "수학Ⅰ": ("12수학Ⅰ", "12수학I"),
    "수학Ⅱ": ("12수학Ⅱ", "12수학II"),
    "미적분": ("12미적",),
    "확률과 통계": ("12확통",),
    "기하": ("12기하",),
    "경제 수학": ("12경수",),
    "실용 수학": ("12실수",),
    "수학과제 탐구": ("12수과",),
    "인공지능 수학": ("12인수",),
    "직무 수학": ("12직수",),
    "수학과 문화": ("12수문",),
    "실용 통계": ("12실통",),
}
FIELD_LABELS = {
    "overview": ("평가개요", "평가내용", "수행과제", "과제내용"),
    "method": ("평가방법", "방법"),
    "timing": ("평가시기", "실시시기", "평가일시횟수", "시기"),
    "weight": ("점수반영비율", "반영비율", "평가비율"),
    # A bare "점수/배점" is normally a rubric column, not the task total.
    "score": ("영역만점", "만점", "총점"),
}
ALL_FIELD_LABELS = {label for labels in FIELD_LABELS.values() for label in labels} | {
    "성취기준",
    "평가기준",
    "평가요소",
    "세부기준",
    "부여점수",
    "관련단원",
    "영역",
    "평가영역",
    "평가영역만점",
    "평가척도",
    "채점기준및배점",
}


@dataclass(frozen=True)
class ParsedAssessmentItem:
    order: int
    title: str
    title_raw: str
    title_basis: str
    extraction_status: str
    source_start: int
    source_end: int
    source_markdown: str
    source_html: str
    rubric_html: str
    overview: str
    method: str
    timing: str
    score: str
    weight: str
    standards: tuple[str, ...]


@dataclass(frozen=True)
class ParsedAssessmentSection:
    subject: str
    boundary_status: str
    source_start: int
    source_end: int
    source_markdown: str
    detected_titles: tuple[str, ...]
    items: tuple[ParsedAssessmentItem, ...]


def compact_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣ⅠⅡ]", "", unicodedata.normalize("NFKC", value))


def subject_code_key(value: str) -> str:
    """Normalize a curriculum-code token without collapsing Roman numerals.

    Ordinary title comparison uses NFKC, but NFKC turns the course numerals
    ``Ⅰ`` and ``Ⅱ`` into ``I`` and ``II``.  A prefix comparison could then read
    a ``수학Ⅱ`` achievement code as ``수학Ⅰ``.  Course identity is a safety
    boundary, so curriculum-code matching preserves those original numerals.
    """

    return re.sub(r"[^0-9A-Za-z가-힣ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]", "", unicodedata.normalize("NFC", value))


def subjects_for_standard_codes(codes: list[str]) -> set[str]:
    """Map codes to subjects using only the most specific matching prefix."""

    return {subject for raw_code in codes for subject in _standard_code_subjects(subject_code_key(raw_code))}


_NORMALIZED_STANDARD_PREFIXES = tuple(
    (subject_code_key(prefix), subject)
    for subject, prefixes in EXPECTED_STANDARD_PREFIXES.items() for prefix in prefixes
)


def _standard_code_subjects(code: str) -> set[str]:
    matches = [(len(prefix), subject) for prefix, subject in _NORMALIZED_STANDARD_PREFIXES if code.startswith(prefix)]
    longest = max((length for length, _ in matches), default=0)
    return {subject for length, subject in matches if length == longest}


def visible_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip(" |#*:-")


def _line_offsets(text: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        result.append((cursor, cursor + len(line), line.rstrip("\r\n")))
        cursor += len(line)
    if not result or result[-1][1] < len(text):
        result.append((cursor, len(text), text[cursor:]))
    return result


def _standalone_course_heading(raw: str) -> str:
    """Return a canonical course name from a source-authored Markdown heading.

    Combined Schoolinfo plans commonly use a short H1 such as ``# 기하`` or
    ``# 확률과 통계 (2학기)``.  Requiring the much longer phrase
    ``교수학습 및 평가계획`` made the parser start at the table of contents
    and then absorb every following course.  Only an exact, standalone heading
    is accepted here; ordinary prose mentions and table cells are ignored.
    """

    match = re.match(r"^\s*#{1,3}\s+(.+?)\s*$", raw)
    if not match:
        return ""
    shown = visible_text(match.group(1))
    shown = re.sub(r"\s*\([^)]*(?:학기|개정)[^)]*\)\s*$", "", shown).strip()
    key = compact_text(shown)
    for course in EXPECTED_STANDARD_PREFIXES:
        if key == compact_text(course):
            return course
    return ""


def subject_local_markdown(full_text: str, subject: str) -> tuple[str, int, int, str]:
    """Return a raw-markdown subject section without flattening its tables."""

    target = compact_text(subject)
    lines = _line_offsets(full_text)

    # A Schoolinfo attachment is often one ZIP containing every subject.  The
    # extractor deliberately preserves a member boundary before each embedded
    # document.  Prefer that source-authored boundary over text heuristics so a
    # math case can never absorb the neighbouring chemistry/English plan.
    zip_members: list[tuple[int, str]] = []
    for index, (_, _, raw) in enumerate(lines):
        match = ZIP_MEMBER_RE.match(raw.strip())
        if match:
            zip_members.append((index, match.group("name")))
    matching_members = [
        position
        for position, (line_index, name) in enumerate(zip_members)
        if target and target in compact_text(name) and "평가" in compact_text(name)
    ]
    if matching_members:
        # Prefer the filename with the least text beyond the requested course.
        # This keeps a generic "수학" case from selecting "경제 수학" merely
        # because that member happened to appear first in the ZIP.
        position = min(
            matching_members,
            key=lambda value: (
                len(compact_text(Path(zip_members[value][1]).stem)) - len(target),
                value,
            ),
        )
        start_index = zip_members[position][0]
        end_index = zip_members[position + 1][0] if position + 1 < len(zip_members) else len(lines)
        start = lines[start_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(full_text)
        return full_text[start:end].strip(), start, end, "zip_member_subject"

    # PDF/HWP converters preserve document headings even when the original
    # attachment contains many mathematics courses.  Use those exact headings
    # before the looser cover-table rules below.  Consecutive semester sections
    # for the same course remain in one local block; the next *different*
    # mathematics course closes it.
    course_headings = [
        (index, course)
        for index, (_, _, raw) in enumerate(lines)
        if (course := _standalone_course_heading(raw))
    ]
    matching_headings = [
        position
        for position, (_, course) in enumerate(course_headings)
        if course == subject
    ]
    if matching_headings:
        position = matching_headings[0]
        start_index = course_headings[position][0]
        end_index = len(lines)
        start_heading = re.match(r"^\s*(#{1,3})\s+", lines[start_index][2])
        start_level = len(start_heading.group(1)) if start_heading else 3
        for next_position in range(position + 1, len(course_headings)):
            line_index, next_course = course_headings[next_position]
            if next_course != subject:
                end_index = line_index
                break
        # A combined plan can place mathematics next to English, arts, or a
        # vocational course.  The canonical list above intentionally knows
        # only mathematics, so also stop at a peer-level heading that visibly
        # opens another course plan.  Without this boundary, a short
        # ``# 공통수학1`` heading could absorb every following subject.
        for line_index in range(start_index + 1, end_index):
            raw = lines[line_index][2]
            heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", raw)
            if not heading or len(heading.group(1)) > start_level:
                continue
            shown = visible_text(heading.group(2))
            compact = compact_text(shown)
            if target in compact:
                continue
            opens_course_plan = (
                "교수학습" in compact
                and "평가" in compact
                and any(term in compact for term in ("계획", "운영", "방법"))
            )
            if opens_course_plan:
                end_index = line_index
                break
        start = lines[start_index][0]
        end = lines[end_index][0] if end_index < len(lines) else len(full_text)
        return full_text[start:end].strip(), start, end, "subject_heading_exact"

    mentions: list[int] = []
    start_index: int | None = None
    for index, (_, _, raw) in enumerate(lines):
        shown = visible_text(raw)
        compact = compact_text(shown)
        # Course identity must occur on a cover/heading line.  Substring-only
        # matching made the short course name "대수" match "기대수행" in every
        # rubric and caused a whole multi-subject ZIP to be treated as 대수.
        course_identity = bool(
            target
            and target in compact
            and (
                any(marker in compact for marker in COURSE_HEADING_MARKERS)
                or bool(re.search(rf"[\[(‘'\"]\s*{re.escape(subject)}\s*[\])’'\"]", shown))
            )
        )
        if course_identity:
            mentions.append(index)
            if start_index is None and any(marker in compact for marker in COURSE_HEADING_MARKERS):
                start_index = index
    if start_index is None:
        if not mentions:
            return full_text, 0, len(full_text), "subject_heading_not_found"
        # A single-subject source often names the subject only in a cover table.
        # Start at that source-authored identity instead of copying unrelated
        # front matter before it.
        start_index = mentions[0]
        search_from = mentions[0] + 1
        status = "subject_mention_only"
    else:
        search_from = start_index + 1
        status = "subject_heading"

    end_index = len(lines)
    for index in range(search_from, len(lines)):
        shown = visible_text(lines[index][2])
        compact = compact_text(shown)
        if (
            target not in compact
            and 3 <= len(compact) <= 120
            and any(marker in compact for marker in COURSE_HEADING_MARKERS)
        ):
            end_index = index
            break
    start = lines[start_index][0] if lines else 0
    end = lines[end_index][0] if end_index < len(lines) else len(full_text)
    return full_text[start:end].strip(), start, end, status


def _anchor_score(line: str) -> int:
    shown = visible_text(line)
    compact = compact_text(shown)
    if "수행평가" not in compact:
        return 0
    if any(
        term in compact
        for term in (
            "참고할것",
            "기본점수",
            "미응시",
            "재응시",
            "결시자",
            "공통적용",
            "유의사항",
            "인정점",
        )
    ):
        return 0
    if "수행평가영역별성취기준" in compact:
        return 110
    if (
        "수행평가세부기준" in compact
        or "수행평가세부계획" in compact
        or "수행평가과제별세부계획" in compact
    ):
        return 105
    if re.fullmatch(r"(?:나|다)?수행평가", compact):
        return 75
    # Many plans use a short source heading such as ``라. 수행평가 영역 및
    # 배점``.  It is a reliable block anchor only when it is visibly a heading,
    # not when the same words occur in prose or a schedule table.
    heading_like = bool(
        re.match(r"^\s*#{1,6}\s+", line)
        or re.match(r"^\s*(?:\d{1,2}|[가-하])\s*[.)]\s*", visible_text(line))
    )
    if (
        heading_like
        and len(compact) <= 60
        and any(term in compact for term in ("세부", "계획", "기준", "영역", "과제", "배점"))
    ):
        return 90
    return 0


def assessment_block(subject_markdown: str) -> tuple[str, int, int, str]:
    lines = _line_offsets(subject_markdown)
    anchors = [(_anchor_score(raw), index) for index, (_, _, raw) in enumerate(lines)]
    anchors = [value for value in anchors if value[0] > 0]
    if not anchors:
        return subject_markdown, 0, len(subject_markdown), "assessment_anchor_not_found"
    best_score = max(score for score, _ in anchors)
    anchor_index = min(index for score, index in anchors if score == best_score)
    end_index = len(lines)
    for index in range(anchor_index + 1, len(lines)):
        raw = lines[index][2]
        if "<" in raw:
            continue
        shown = visible_text(raw)
        if not BLOCK_END_RE.search(shown):
            continue
        if re.match(r"^(?:#{1,6}\s*)?(?:\|\s*)?(?:\d+|[가-하])\s*[.)|]", raw.strip()):
            end_index = index
            break
    start = lines[anchor_index][0]
    end = lines[end_index][0] if end_index < len(lines) else len(subject_markdown)
    return subject_markdown[start:end].strip(), start, end, "assessment_anchor"


def _clean_heading_title(raw: str) -> tuple[str, str]:
    title_raw = visible_text(raw)
    match = ITEM_PREFIX_RE.match(title_raw)
    title = match.group("title").strip() if match else title_raw
    title = re.sub(r"^수행평가\s*\(\s*\d+\s*\)\s*[-:–—]?\s*", "", title)
    title = re.sub(
        r"\s*\([^)]*(?:\d+(?:\.\d+)?\s*(?:점|%)|만점|반영\s*비율)[^)]*\)\s*$",
        "",
        title,
    )
    # Some plans append the area score without the word '점' (e.g. '(20)')
    # or as '20(점) (논술형)'.  Values 1-4 are often source numbering, so only
    # strip score-sized values while preserving the exact source in title_raw.
    title = re.sub(
        r"\s*\(\s*(?:[5-9]|[1-9]\d|100)\s*\)\s*$",
        "",
        title,
    )
    title = re.sub(
        r"\s+(?:[5-9]|[1-9]\d|100)\s*\(\s*점\s*\)"
        r"(?=\s*(?:\([^)]*\))?\s*$)",
        "",
        title,
    )
    # PDF-to-Markdown conversion often collapses a section heading and the
    # following lettered task name onto one line. Keep only the source-authored
    # task portion instead of publishing "수행평가 세부 계획 가." as its name.
    title = re.sub(
        r"^수행\s*평가\s*세부\s*(?:계획|기준)"
        r"(?:\s*\([^)]*\))?\s*(?:[가-하]\s*[.)]|\([가-하]\))\s*",
        "",
        title,
    )
    title = re.sub(r"^수행\s*평가\s*\d+\s*[:：]\s*", "", title)
    title = re.sub(r"^수행\s*평가\s*영역\s*\d+\s*[:：]\s*", "", title)
    title = re.sub(r"^\d+\s*순위\s*\([^)]*반영\s*비율[^)]*\)\s*[:：]\s*", "", title)
    title = re.sub(r"^\[\s*(?:서[·ㆍ]?논술형|서술형|논술형)\s*\]\s*", "", title)
    title = re.sub(r"\s*\(\s*평가\s*시기\b.*$", "", title)
    scored_description = re.fullmatch(
        r"(.{2,}?)\s*\([^)]*(?:\d+(?:\.\d+)?\s*(?:점|%))[^)]*\)\s*[:：]\s*.+",
        title,
    )
    if scored_description:
        title = scored_description.group(1)
    task_with_rubric_suffix = re.fullmatch(r"(.+?)\s*수행\s*평가\s*기준", title)
    if task_with_rubric_suffix:
        candidate = task_with_rubric_suffix.group(1)
        if (
            len(compact_text(candidate)) >= 2
            and compact_text(candidate) not in STRUCTURAL_EXACT_COMPACT
        ):
            title = candidate
    task_with_criteria_suffix = re.fullmatch(r"(.+?)\s*평가\s*기준", title)
    if task_with_criteria_suffix:
        candidate = task_with_criteria_suffix.group(1)
        if (
            len(compact_text(candidate)) >= 2
            and compact_text(candidate) not in STRUCTURAL_EXACT_COMPACT
        ):
            title = candidate
    return re.sub(r"\s+", " ", title).strip(" -:|"), title_raw


def _valid_title(title: str) -> bool:
    compact = compact_text(title)
    if not 2 <= len(compact) <= 100:
        return False
    if GENERIC_TITLE_RE.fullmatch(title) or re.fullmatch(r"[0-9점%./~\s]+", title):
        return False
    return not (len(compact) > 4 and bool(re.search(r"(?:상|중|하)\s*$", title)))


def heading_title_is_structural(title: str) -> bool:
    """Return true when a numbered heading describes document structure, not a task.

    These strings are common subheadings *inside* one assessment. Publishing
    them as assessment names made a rubric or policy sentence appear to be a
    separate task. Long imperative/policy sentences are also kept only as raw
    source unless an explicit title cell confirms a real task name.
    """

    clean = re.sub(r"\s+", " ", title).strip()
    structural_clean = re.sub(r"^(?:\d+|[가-하])\s*[.)]\s*", "", clean)
    structural_clean = re.sub(r"\s*\(※[^)]*\)\s*$", "", structural_clean)
    # PDF/HWP converters frequently leave the comma from a numbered outline
    # (for example ``12. 학기 단위 성취수준 설정,``) or collapse the next
    # numbered heading onto the same line.  Punctuation is not evidence that a
    # document-structure heading became an assessment title.
    structural_clean = structural_clean.strip(" ,，:：;；.-")
    compact = compact_text(structural_clean)
    return bool(
        compact in STRUCTURAL_EXACT_COMPACT
        or STRUCTURAL_HEADING_RE.fullmatch(structural_clean)
        or re.match(
            r"^(?:교육과정\s*)?성취\s*기준\s*[:：]?\s*\[(?:10|12)",
            structural_clean,
        )
        or re.match(
            r"^(?:학기\s*단위\s*)?성취\s*수준(?:\s*설정.*)?$|"
            r"^최소\s*성취\s*수준(?:\s*(?:설정|진술).*)?$",
            structural_clean,
        )
        or re.fullmatch(r"(?:일반|공통|기타)\s*사항|영역별", structural_clean)
        or re.match(r"^\[(?:10|12)[^\]]+\](?:\s*[~\\-].*)?$", structural_clean)
        or re.match(
            r"^(?:성취\s*기준\s*및\s*성취\s*수준|수강생.*통합\s*산출\s*여부)",
            structural_clean,
        )
        or re.search(
            r"(?:동일\s*학년\s*동일\s*교과|신체\s*장애\s*학생|"
            r"통합반\s*선생님|채점\s*기준표)",
            structural_clean,
        )
        or re.fullmatch(
            r"(?:수행평가\s*과제별\s*세부\s*계획|평가\s*방법\s*및\s*채점\s*기준\s*배점|"
            r"채점\s*기준\s*및\s*배점|성취\s*기준\s*및\s*평가\s*기준|"
            r"평가\s*내용\s*및\s*방법|실시\s*시기\s*및\s*횟수|"
            r"평가\s*관점[·ㆍ]?\s*요소|수행\s*수준\s*\(채점\s*기준\)\s*및\s*배점)",
            structural_clean,
        )
        or re.match(
            r"^(?:수행평가에서\s*인공지능|수행평가\s*유형은|"
            r"수행평가\s*결과물에\s*AI|"
            r"수행평가\s*세부\s*계획과\s*채점|수행평가의\s*영역|"
            r"전[·ㆍ]?편입생|영역\s*만점은|질병\s*결석|최소\s*성취수준|기준\s*성취율)",
            structural_clean,
        )
        or re.search(
            r"(?:AI|인공지능).*(?:활용\s*(?:가능|금지|허용)|사용\s*금지|"
            r"힌트\s*요청|활용\s*내역)",
            structural_clean,
            re.I,
        )
        or re.search(
            r"(?:교과협의회|학업성적(?:관리)?|관리위원회|심의\s*후|"
            r"평가\s*관련\s*제반\s*문제|평가\s*결과의?\s*활용)",
            structural_clean,
        )
        or re.match(
            r"^평소\s*수업\s*활동이\s*자연스럽게\s*평가로\s*이어지도록",
            structural_clean,
        )
        or re.match(
            r"^(?:수행평가\s*(?:결시자의|영역별\s*특성|시간에|에\s*참여한|"
            r"의\s*(?:목표|반영\s*비율)|를\s*할\s*때|는|인공지능|결과물은)|"
            r"결석의\s*경우|결시(?:생|\s*\()|영역의\s*특성|질병\s*및\s*인정\s*결석|"
            r"특수교육\s*대상자|AI(?:는|의\s*활용|를\s*활용)|교과의\s*특성을|"
            r"전입생이|성취기준에\s*근거한\s*평가의|정기시험(?:은|에서)|"
            r"내용\s*영역,\s*성취기준|모둠토의|포트폴리오에서|"
            r"성취기준별\s*성취수준에\s*따른\s*수행\s*정도|출제\s*원안에는|"
            r"모든\s*출제\s*원안|객관적이고\s*공정한\s*채점\s*기준|"
            r"학생이\s*성취기준에|학생의\s*수업\s*시간\s*활동|원안\s*제출\s*시|"
            r"5지\s*선다형|평가\s*\(정기시험\s*및\s*수행평가\)의|"
            r"성취기준을\s*분석하여|비고\s*[:：]|평가\s*요소\s*[:：])",
            structural_clean,
        )
        or re.match(
            r"^(?:최하\s*\d+점부터|[「『]?공교육\s*정상화\s*촉진)",
            structural_clean,
        )
        or re.search(
            r"(?:제출\s*금지|구분하여\s*명시|해당\s*없음)$",
            structural_clean,
        )
        or re.search(
            r"(?:수행하였는가|활동하고\s*있는가|명확하게.*있는가)\s*\?$",
            structural_clean,
        )
        or (
            len(compact) >= 10
            and re.search(
                r"(?:한다|된다|따른다|바란다|않는다|서술함|"
                r"할수있다|부여할수있다)$",
                compact,
            )
        )
    )


def segment_subject_alignment(segment: str, subject: str) -> str:
    """Classify achievement-code evidence for a short-name subject boundary."""

    prefixes = EXPECTED_STANDARD_PREFIXES.get(subject)
    if not prefixes:
        return "unknown"
    shown = unicodedata.normalize("NFC", visible_text(segment))
    # Some school plans spell a 2022 course code with an extra separator after
    # the grade band (for example ``[12-대수01-05]``).  It denotes the same
    # course as ``[12대수01-05]`` and must remain usable as source evidence.
    codes = [
        subject_code_key(match)
        for match in re.findall(
            r"\[\s*((?:10|12)(?:\s*-\s*)?[^\]\-]{1,20})\s*-\s*\d",
            shown,
        )
    ]
    if codes and all(_standard_code_subjects(code) == {subject} for code in codes):
        return "expected"
    # An explicit achievement-standard code is stronger boundary evidence than
    # a short subject-name mention.  If the code cannot confirm the requested
    # mathematics course, keep the section out of the public catalogue even
    # when the code belongs to a non-mathematics subject that is intentionally
    # absent from ``EXPECTED_STANDARD_PREFIXES``.
    return "other" if codes else "unknown"


def explicit_segment_title(segment: str) -> str:
    """Read an assessment name only from an explicit source-table label.

    The first non-empty cell after labels such as ``평가 영역명`` or
    ``수행평가명`` is source-authored evidence. Metadata cells (score, timing,
    method, and so on) terminate the search so merged tables cannot leak a
    neighbouring field into the title.
    """

    def clean_candidate(candidate: str) -> str:
        return re.split(
            r"\s+(?:(?:영역\s*)?만점|학기)(?:\s|$)",
            candidate,
            maxsplit=1,
        )[0].strip(" |")

    def usable(candidate: str) -> bool:
        compact = compact_text(candidate)
        return bool(
            candidate
            and 2 <= len(compact) <= 120
            and not re.search(r"^(?:10|12)[0-9A-Za-z가-힣ⅠⅡ]", compact)
            and not TITLE_VALUE_STOP_LABEL_RE.fullmatch(compact)
            and not NON_TASK_TITLE_RE.fullmatch(candidate.strip())
            and not EXPLICIT_TITLE_LABEL_RE.fullmatch(compact)
            and not heading_title_is_structural(candidate)
            and _valid_plan_title(candidate)
        )

    def source_spelling(candidate: str) -> str:
        """Restore exact source glyphs lost by normalized table parsing."""

        candidate_key = compact_text(candidate)
        for match in re.finditer(
            r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>",
            segment,
            flags=re.I | re.S,
        ):
            source_candidate = visible_text(match.group(1)).strip(" |")
            if compact_text(source_candidate) == candidate_key and usable(source_candidate):
                return source_candidate
        return candidate

    for rows in _source_tables(segment):
        for row_index, row in enumerate(rows[:8]):
            values = [visible_text(cell) for cell in row]
            labels = [compact_text(value) for value in values]
            for index, label in enumerate(labels):
                if not EXPLICIT_TITLE_LABEL_RE.fullmatch(label):
                    continue
                # Detailed item tables usually place the title immediately to
                # the right of the label. Stop if the next populated cell is
                # another metadata header; that row is a column header, not a
                # title/value pair.
                has_horizontal_value = False
                for following in range(index + 1, len(values)):
                    candidate = clean_candidate(values[following])
                    candidate_label = labels[following]
                    if not candidate:
                        continue
                    has_horizontal_value = True
                    if (
                        candidate_label in TITLE_VALUE_STOP_LABELS
                        or TITLE_VALUE_STOP_LABEL_RE.fullmatch(candidate_label)
                        or EXPLICIT_TITLE_LABEL_RE.fullmatch(candidate_label)
                    ):
                        break
                    if usable(candidate):
                        return source_spelling(candidate)
                    break

                # A label/value row can contain a generic assessment area
                # (for example, '학습과정평가') followed by a later explicit
                # '수행과제' row.  It is not a summary-table column header,
                # so do not scan its unrelated first-column values vertically.
                if has_horizontal_value:
                    continue

                # In a summary table the label is a column header. Accept a
                # vertical value only when exactly one distinct performance
                # task remains after excluding written exams and field labels;
                # multiple values are deliberately left as a review bundle.
                vertical: list[str] = []
                seen: set[str] = set()
                for following_row in rows[row_index + 1 :]:
                    if index >= len(following_row):
                        continue
                    candidate = clean_candidate(visible_text(following_row[index]))
                    key = compact_text(candidate)
                    if usable(candidate) and key not in seen:
                        seen.add(key)
                        vertical.append(candidate)
                if len(vertical) == 1:
                    return source_spelling(vertical[0])

        # A common rubric layout names the assessment in the first data cell
        # under an explicit '영역(만점)' header.  This differs from an ordinary
        # 평가요소 table: the same header row also names the item, criterion,
        # and score columns.  The first populated area cell is therefore a
        # source-authored assessment name, not a rubric dimension inferred by
        # the parser.
        for row_index, row in enumerate(rows[:-1]):
            labels = [compact_text(visible_text(value)) for value in row]
            if not labels or labels[0] not in {"영역만점", "평가영역만점"}:
                continue
            support = sum(
                any(marker in label for marker in ("평가항목", "평가요소", "채점기준", "배점"))
                for label in labels[1:]
            )
            if support < 2:
                continue
            for following_row in rows[row_index + 1 :]:
                if not following_row:
                    continue
                candidate = clean_candidate(visible_text(following_row[0]))
                if usable(candidate):
                    return source_spelling(candidate)
                if candidate:
                    break
    return ""


def _heading_candidates(block: str) -> list[tuple[int, int, str, str]]:
    lines = _line_offsets(block)
    preliminary: list[tuple[int, int, str, str]] = []
    table_depth = 0
    for index, (start, _, raw) in enumerate(lines):
        opens = len(re.findall(r"<table\b", raw, flags=re.I))
        closes = len(re.findall(r"</table>", raw, flags=re.I))
        outside_table = table_depth == 0
        # Markdown pipe rows are tables too.  Their numbered rubric cells are
        # never source headings, even though they may begin with "1." or "가.".
        if outside_table and not raw.lstrip().startswith("|"):
            title, title_raw = _clean_heading_title(raw)
            if ITEM_PREFIX_RE.match(visible_text(raw)) and _valid_title(title):
                preliminary.append((index, start, title, title_raw))
        table_depth += opens - closes
        table_depth = max(0, table_depth)

    accepted: list[tuple[int, int, str, str]] = []
    for position, candidate in enumerate(preliminary):
        line_index, start, title, title_raw = candidate
        next_start = preliminary[position + 1][1] if position + 1 < len(preliminary) else len(block)
        segment = block[start:next_start]
        markers = set(match.group(0) for match in ASSESSMENT_MARKER_RE.finditer(segment))
        performance_markers = set(
            match.group(0) for match in PERFORMANCE_MARKER_RE.finditer(segment)
        )
        # A curriculum unit followed only by a standards/achievement-level
        # table is not a performance assessment.  The former rule accepted
        # these headings merely because a table was present, publishing unit
        # names such as "다항식" or "수열" as task names.
        if not performance_markers:
            continue
        if len(markers) >= 2 or ("<table" in segment.lower() and explicit_segment_title(segment)):
            accepted.append((line_index, start, title, title_raw))
    return accepted


def _markdown_pipe_table_fragments(value: str) -> list[str]:
    lines = value.splitlines()
    fragments: list[str] = []
    index = 0
    while index + 1 < len(lines):
        if not (
            lines[index].strip().startswith("|") and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1])
        ):
            index += 1
            continue
        start = index
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            index += 1
        fragments.append("\n".join(lines[start:index]))
    return fragments


@lru_cache(maxsize=64)
def _source_tables(value: str) -> list[list[list[str]]]:
    """Return HTML and PDF-style Markdown tables with their source cells."""

    tables = html_tables(value)
    for fragment in _markdown_pipe_table_fragments(value):
        rows = fragment.splitlines()
        parsed = [_split_pipe_row(rows[0])]
        parsed.extend(_split_pipe_row(row) for row in rows[2:])
        if parsed:
            tables.append(parsed)
    return tables


PLAN_TITLE_COLUMN_LABELS = {
    "평가내용",
    "수행평가명",
    "수행평가영역",
    "수행평가과제",
    "평가영역",
    "평가과제",
    "과제명",
}


@lru_cache(maxsize=16)
def _table_fragments_with_spans(value: str) -> list[tuple[int, int, str]]:
    fragments = [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(r"<table\b.*?</table>", value, flags=re.I | re.S)
    ]
    lines = _line_offsets(value)
    index = 0
    while index + 1 < len(lines):
        raw = lines[index][2]
        if not (raw.strip().startswith("|") and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1][2])):
            index += 1
            continue
        start = lines[index][0]
        index += 2
        while index < len(lines) and lines[index][2].strip().startswith("|"):
            index += 1
        end = lines[index - 1][1]
        fragments.append((start, end, value[start:end]))
    return sorted(fragments, key=lambda fragment: (fragment[0], fragment[1]))


def _row_table_html(header: list[str], row: list[str]) -> str:
    width = max(len(header), len(row))
    header_values = [*header, *([""] * (width - len(header)))]
    row_values = [*row, *([""] * (width - len(row)))]

    def cell(value: str) -> str:
        return html.escape(visible_text(value)).replace("\n", "<br>")

    return (
        "<table><thead><tr>"
        + "".join(f"<th>{cell(value)}</th>" for value in header_values)
        + "</tr></thead><tbody><tr>"
        + "".join(f"<td>{cell(value)}</td>" for value in row_values)
        + "</tr></tbody></table>"
    )


def _source_spelling_for_table_value(fragment: str, candidate: str) -> str:
    key = compact_text(candidate)
    for match in re.finditer(r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", fragment, flags=re.I | re.S):
        source_value = visible_text(match.group(1))
        if compact_text(source_value) == key:
            return source_value
    for raw in fragment.splitlines():
        for value in _split_pipe_row(raw) if raw.strip().startswith("|") else []:
            source_value = visible_text(value)
            if compact_text(source_value) == key:
                return source_value
    return candidate


def _matched_rubric_html(block: str, title: str) -> str:
    title_key = compact_text(title)
    criteria_labels = {
        "채점기준", "평가기준", "평가척도", "점수부여기준", "세부평가기준",
        "채점기준및배점", "평가관점및배점기준", "수행수준채점기준및배점", "수행평가채점기준",
    }
    matched: list[str] = []
    for _, _, fragment in _table_fragments_with_spans(block):
        tables = _source_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        for header_index, header in enumerate(rows[:-1]):
            labels = [compact_text(value) for value in header]
            if not criteria_labels.intersection(labels):
                continue
            for source_row in rows[header_index + 1 :]:
                # A rubric row can label a task with its total in parentheses.
                # Task names mentioned in teaching notes do not identify rows.
                row_titles = {
                    compact_text(re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*점\s*\)\s*$", "", visible_text(value)))
                    for value in source_row
                }
                if not title_key or title_key not in row_titles:
                    continue
                rendered = _row_table_html(header, source_row)
                if rendered not in matched:
                    matched.append(rendered)
            if matched:
                break
    return "\n".join(matched)


def _instruction_schedule_rows(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    labels = {compact_text(cell) for cell in rows[0]}
    return "수업방법" in labels and bool({"진도계획", "수업평가연계의주안점"}.intersection(labels))


def _expected_code_table_items(full_text: str, subject: str) -> list[ParsedAssessmentItem]:
    """Recover explicit task tables when a combined document lost its headings.

    Achievement-standard codes are used only as a rejection/identity boundary:
    every code in the table must belong to the requested mathematics course.
    The title still has to come from an explicit source label.
    """

    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(full_text):
        if segment_subject_alignment(fragment, subject) != "expected":
            continue
        title = explicit_segment_title(fragment)
        if not title:
            continue
        display_title, _ = _clean_heading_title(title)
        key = compact_text(display_title)
        if not key or key in seen:
            continue
        source_html = markdown_fragment_to_html(fragment)
        fields = _exact_fields(fragment)
        rubric_html = _rubric_html(fragment) or _matched_rubric_html(full_text, title)
        output.append(
            ParsedAssessmentItem(
                order=len(output) + 1,
                title=display_title,
                title_raw=title,
                title_basis="table",
                extraction_status="bounded",
                source_start=start,
                source_end=end,
                source_markdown=fragment,
                source_html=source_html,
                rubric_html=rubric_html,
                overview=str(fields["overview"]),
                method=str(fields["method"]),
                timing=str(fields["timing"]),
                score=str(fields["score"]),
                weight=str(fields["weight"]),
                standards=tuple(str(value) for value in fields["standards"]),
            )
        )
        seen.add(key)
    return output


def _explicit_local_table_items(
    subject_markdown: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Recover a labelled assessment table inside a reliable course section."""

    if subject_status not in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }:
        return []
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(subject_markdown):
        alignment = segment_subject_alignment(fragment, subject)
        if alignment == "other":
            continue
        compact_fragment = compact_text(visible_text(fragment))
        strong_label = any(
            label in compact_fragment
            for label in (
                "평가영역명",
                "평가영역",
                "영역만점",
                "수행평가명",
                "수행평가과제",
                "평가과제",
                "수행과제",
                "과제명",
            )
        )
        evidence_markers = sum(
            marker in compact_fragment
            for marker in (
                "성취기준",
                "평가방법",
                "반영비율",
                "채점기준",
                "평가요소",
                "배점",
                "만점",
            )
        )
        if not strong_label or evidence_markers < 2:
            continue
        title = explicit_segment_title(fragment)
        if not title:
            continue
        display_title, _ = _clean_heading_title(title)
        key = compact_text(display_title)
        if not key or key in seen:
            continue
        source_html = markdown_fragment_to_html(fragment)
        fields = _exact_fields(fragment)
        rubric_html = _rubric_html(fragment) or _matched_rubric_html(subject_markdown, title)
        output.append(
            ParsedAssessmentItem(
                order=len(output) + 1,
                title=display_title,
                title_raw=title,
                title_basis="table",
                extraction_status="bounded",
                source_start=source_offset + start,
                source_end=source_offset + end,
                source_markdown=fragment,
                source_html=source_html,
                rubric_html=rubric_html,
                overview=str(fields["overview"]),
                method=str(fields["method"]),
                timing=str(fields["timing"]),
                score=str(fields["score"]),
                weight=str(fields["weight"]),
                standards=tuple(str(value) for value in fields["standards"]),
            )
        )
        seen.add(key)
    return output


def _matrix_table_items(
    value: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Split a source matrix whose columns distinguish written/performance tests."""

    boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(value):
        tables = _source_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        category_row: list[str] | None = None
        title_row: list[str] | None = None
        for row in rows:
            if not row:
                continue
            first = compact_text(row[0])
            row_labels = [compact_text(cell) for cell in row]
            if first in {"평가종류", "평가구분", "평가유형", "구분"} and any(
                "수행평가" in label for label in row_labels[1:]
            ):
                category_row = row
            if first in {"평가영역", "평가영역명", "평가내용", "수행평가명", "과제명", "횟수영역"}:
                title_row = row
        if category_row is None or title_row is None:
            continue
        performance_columns = [
            index
            for index, cell in enumerate(category_row[1:], 1)
            if "수행평가" in compact_text(cell)
        ]
        for column in performance_columns:
            if column >= len(title_row):
                continue
            candidate = visible_text(title_row[column]).strip()
            key = compact_text(candidate)
            if not key or key in seen or not _valid_plan_title(candidate):
                continue
            pairs: list[tuple[str, str]] = []
            for row in rows:
                if not row or column >= len(row):
                    continue
                label = visible_text(row[0]).strip()
                cell_value = visible_text(row[column]).strip()
                if not label or not cell_value or len(compact_text(label)) > 40:
                    continue
                pairs.append((label, cell_value))
            if len(pairs) < 3:
                continue
            matrix_html = "<table><tbody>" + "".join(
                f"<tr><th>{html.escape(label)}</th><td>{html.escape(cell_value)}</td></tr>"
                for label, cell_value in pairs
            ) + "</tbody></table>"
            alignment = segment_subject_alignment(matrix_html, subject)
            if alignment == "other" or (alignment == "unknown" and not boundary_reliable):
                continue
            title = _source_spelling_for_table_value(fragment, candidate)
            fields = _exact_fields(matrix_html)
            # A matrix can show the total weight of all performance tasks above
            # the separate weight in each task's own score cell.
            own_weight = next(
                (_first_pattern([value], WEIGHT_VALUE_RE) for label, value in pairs
                 if "만점" in compact_text(label) and "반영비율" in compact_text(label)),
                "",
            )
            if own_weight:
                fields["weight"] = own_weight
            rubric_html = _matched_rubric_html(value, title)
            source_html = (
                matrix_html
                if not rubric_html
                else matrix_html + "\n" + rubric_html
            )
            output.append(
                ParsedAssessmentItem(
                    order=len(output) + 1,
                    title=title,
                    title_raw=title,
                    title_basis="table",
                    extraction_status="bounded",
                    source_start=source_offset + start,
                    source_end=source_offset + end,
                    source_markdown=source_html,
                    source_html=source_html,
                    rubric_html=rubric_html,
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(item) for item in fields["standards"]),
                )
            )
            seen.add(key)
    return output


def _hinted_table_items(
    value: str,
    subject: str,
    subject_status: str,
    source_offset: int,
    title_hints: tuple[str, ...],
) -> list[ParsedAssessmentItem]:
    """Validate prior source-table candidates against the full original table."""

    if not title_hints:
        return []
    boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    usable_hints = [
        hint.strip()
        for hint in title_hints
        if _valid_plan_title(hint.strip()) and not heading_title_is_structural(hint.strip())
    ]
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(value):
        tables = _source_tables(fragment)
        if not tables or _instruction_schedule_rows(tables[0]):
            continue
        cells = [cell for row in tables[0] for cell in row]
        # A matrix shared with written exams needs a task-specific column.
        # A matching title in the table alone cannot identify its scores or dates.
        category_labels = ({re.sub(r"\d+$", "", compact_text(cell)) for cell in row} for row in tables[0])
        if any("수행평가" in labels and {"정기시험", "지필평가"}.intersection(labels) for labels in category_labels):
            continue
        compact_cells = [compact_text(cell) for cell in cells]
        compact_fragment = compact_text(visible_text(fragment))
        evidence_markers = sum(
            marker in compact_fragment
            for marker in (
                "성취기준",
                "평가방법",
                "반영비율",
                "채점기준",
                "평가요소",
                "배점",
                "만점",
            )
        )
        if evidence_markers < 2:
            continue
        alignment = segment_subject_alignment(fragment, subject)
        if alignment == "other" or (alignment == "unknown" and not boundary_reliable):
            continue
        for hint in usable_hints:
            key = compact_text(hint)
            if not key or key in seen:
                continue
            matching_cell = next(
                (
                    cell
                    for cell, cell_key in zip(cells, compact_cells, strict=False)
                    if cell_key == key
                    or (
                        len(key) >= 6
                        and key in cell_key
                        and len(cell_key) - len(key) <= 16
                    )
                ),
                "",
            )
            if not matching_cell:
                continue
            title = _source_spelling_for_table_value(fragment, matching_cell)
            source_html = markdown_fragment_to_html(fragment)
            fields = _exact_fields(fragment)
            rubric_html = _matched_rubric_html(value, title) or _rubric_html(fragment)
            output.append(
                ParsedAssessmentItem(
                    order=len(output) + 1,
                    title=title,
                    title_raw=title,
                    title_basis="table",
                    extraction_status="bounded",
                    source_start=source_offset + start,
                    source_end=source_offset + end,
                    source_markdown=fragment,
                    source_html=source_html,
                    rubric_html=rubric_html,
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(item) for item in fields["standards"]),
                )
            )
            seen.add(key)
    return output


def _summary_table_items(
    block: str,
    subject: str,
    subject_status: str,
    source_offset: int,
) -> list[ParsedAssessmentItem]:
    """Recover individually source-bounded rows from explicit plan tables.

    This path never turns a nearby heading or prose phrase into a title.  It
    requires an explicit task-name column and retains only that source row plus
    its source header.  It is especially important for PDF plans whose two or
    three assessments are rows in one table rather than numbered subsections.
    """

    subject_boundary_reliable = subject_status in {
        "subject_heading",
        "subject_heading_exact",
        "zip_member_subject",
    }
    output: list[ParsedAssessmentItem] = []
    seen: set[str] = set()
    for start, end, fragment in _table_fragments_with_spans(block):
        tables = _source_tables(fragment)
        if not tables:
            continue
        rows = tables[0]
        for header_index, header in enumerate(rows[:-1]):
            labels = [compact_text(value) for value in header]
            plan_markers = any(
                marker in label
                for label in labels
                for marker in ("성취기준", "반영비율", "평가방법", "평가시기", "만점")
            )
            rubric_like_header = any(
                "채점기준" in label for label in labels
            ) or (
                any("평가요소" in label for label in labels) and not plan_markers
            )
            if rubric_like_header:
                # Rows under a rubric header are criteria/dimensions, not
                # additional performance-assessment names.  Real task names
                # are recovered from the plan table or their own heading.
                continue
            summary_markers = any(
                marker in label
                for label in labels
                for marker in ("반영비율", "평가방법", "평가시기", "만점")
            )
            title_columns = []
            for index, label in enumerate(labels):
                if label not in PLAN_TITLE_COLUMN_LABELS:
                    continue
                if label in {"평가영역", "수행평가영역"} and not summary_markers:
                    continue
                title_columns.append(index)
            if not title_columns:
                continue
            evidence_columns = sum(
                bool(
                    label in ALL_FIELD_LABELS
                    or any(
                        marker in label
                        for marker in (
                            "성취기준",
                            "평가방법",
                            "평가요소",
                            "채점기준",
                            "배점",
                            "만점",
                            "반영비율",
                            "시기",
                        )
                    )
                )
                for label in labels
            )
            if evidence_columns < 1:
                continue
            for source_row in rows[header_index + 1 :]:
                for column in title_columns:
                    if column >= len(source_row):
                        continue
                    candidate = visible_text(source_row[column]).strip()
                    key = compact_text(candidate)
                    if not key or key in seen or not _valid_plan_title(candidate):
                        continue
                    row_html = _row_table_html(header, source_row)
                    alignment = segment_subject_alignment(row_html, subject)
                    if alignment == "other" or (
                        alignment == "unknown" and not subject_boundary_reliable
                    ):
                        continue
                    populated_other = sum(
                        bool(visible_text(value))
                        for index, value in enumerate(source_row)
                        if index != column
                    )
                    if populated_other < 1:
                        continue
                    title = _source_spelling_for_table_value(fragment, candidate)
                    fields = _exact_fields(row_html)
                    matched_rubric = _matched_rubric_html(block, title)
                    source_html = (
                        row_html
                        if not matched_rubric or matched_rubric == row_html
                        else row_html + "\n" + matched_rubric
                    )
                    output.append(
                        ParsedAssessmentItem(
                            order=len(output) + 1,
                            title=title,
                            title_raw=title,
                            title_basis="table",
                            extraction_status="bounded",
                            source_start=source_offset + start,
                            source_end=source_offset + end,
                            source_markdown=source_html,
                            source_html=source_html,
                            rubric_html=(
                                matched_rubric or row_html
                                if any(
                                    "채점기준" in label or "평가기준" in label
                                    for label in labels
                                )
                                else matched_rubric
                            ),
                            overview=str(fields["overview"]),
                            method=str(fields["method"]),
                            timing=str(fields["timing"]),
                            score=str(fields["score"]),
                            weight=str(fields["weight"]),
                            standards=tuple(str(value) for value in fields["standards"]),
                        )
                    )
                    seen.add(key)
    return output


def _plan_titles(subject_markdown: str) -> list[str]:
    """Read explicit assessment-name cells from plan tables without guessing."""

    titles: list[str] = []
    for rows in _source_tables(subject_markdown):
        for row_index, row in enumerate(rows):
            labels = [compact_text(cell) for cell in row]
            content_columns = [
                index
                for index, label in enumerate(labels)
                if label in {"평가내용", "수행평가명", "수행평가영역", "평가영역", "과제명"}
            ]
            for column in content_columns:
                for following in rows[row_index + 1 :]:
                    if column >= len(following):
                        continue
                    candidate = visible_text(following[column])
                    if _valid_plan_title(candidate):
                        titles.append(candidate)
            if "평가요소방법" in labels and any(label == "수행평가" for label in labels):
                for index, label in enumerate(labels):
                    if label != "수행평가" or index >= len(row):
                        continue
                    candidate = visible_text(row[index])
                    if _valid_plan_title(candidate):
                        titles.append(candidate)
            for index, label in enumerate(labels[:-1]):
                if label in {"수행평가명", "수행평가과제명", "평가과제명", "과제명"}:
                    for candidate_cell in row[index + 1 :]:
                        candidate = visible_text(candidate_cell)
                        if _valid_plan_title(candidate):
                            titles.append(candidate)
    output: list[str] = []
    seen: set[str] = set()
    for title in titles:
        key = compact_text(title)
        if key and key not in seen:
            seen.add(key)
            output.append(title)
    return output


def _valid_plan_title(value: str) -> bool:
    compact = compact_text(value)
    if not _valid_title(value):
        return False
    return not bool(
        len(compact) > 60
        or re.search(r"[.。]$", value.strip())
        or
        compact
        in {
            "수행평가",
            "평가영역",
            "영역만점",
            "평가내용",
            "평가항목",
            "평가요소",
            "채점기준",
            "배점",
            "평소",
            "단원",
            "수준",
            "학습",
            "직무",
            "그외",
            "수학과",
            "점수점",
            "평가만점",
            "평가방법",
            "반영비율",
            "평가시기",
            "평가요소방법",
            "정기시험",
            "학습내용",
        }
        or re.search(r"(?:평가|반영)\s*비율|\d+\s*(?:점|%)$", value)
        or re.fullmatch(
            r"(?:공통수학[12]\s*전체|(?:정기\s*)?\d+\s*차\s*시험|중간|기말|"
            r"[IVⅠⅡⅢⅣ]+)",
            value.strip(),
        )
        or re.fullmatch(r"(?:프로젝트|포트폴리오|서술형|논술형|교사\s*관찰)\s*평가", value)
    )


def _unique_values(values: list[str], limit: int = 8) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip(" |")
        key = compact_text(clean)
        if not clean or not key or key in seen:
            continue
        seen.add(key)
        output.append(clean)
        if len(output) >= limit:
            break
    return output


METHOD_TERMS = (
    "서술·논술", "서술ㆍ논술", "서술･논술", "구술·발표", "구술ㆍ발표",
    "구술･발표", "토의·토론", "토의ㆍ토론", "토의･토론", "조사·관찰보고서",
    "조사ㆍ관찰보고서", "조사･관찰보고서", "실험·실습", "실험ㆍ실습",
    "실험･실습", "실기·시연", "실기ㆍ시연", "실기･시연", "포트폴리오", "프로젝트",
    "교사 관찰 및 기록", "교사평가", "자기평가", "동료평가", "개별수행",
    "모둠수행", "원점수(합산)", "평균점", "최고점", "환산점", "논술",
    "서술형", "논술형", "선택형", "관찰평가", "보고서", "발표", "토론",
    "실습", "에세이", "기타", "교사",
)
METHOD_SUBLABELS = {
    "유형", "평가유형", "과제유형", "주체", "평가주체", "방식", "평가방식",
    "수행방식", "점수부여", "점수부여방법", "평가방법", "방법",
    "진도계획", "수업방법", "수업평가연계의주안점", "정기시험", "지필평가",
}
METHOD_SEPARATOR_RE = r"[·ㆍ･・‧]"
METHOD_TERM_RE = (
    r"(?:서\s*" + METHOD_SEPARATOR_RE + r"\s*논술|"
    r"서술\s*" + METHOD_SEPARATOR_RE + r"\s*논술|"
    r"구술\s*" + METHOD_SEPARATOR_RE + r"\s*발표|"
    r"토의\s*" + METHOD_SEPARATOR_RE + r"\s*토론|"
    r"토론\s*" + METHOD_SEPARATOR_RE + r"\s*토의|"
    r"조사\s*" + METHOD_SEPARATOR_RE + r"\s*관찰보고서|"
    r"실험\s*" + METHOD_SEPARATOR_RE + r"\s*실습|"
    r"실기\s*" + METHOD_SEPARATOR_RE + r"\s*시연|"
    r"교사\s*관찰\s*및\s*기록|교사\s*평가|관찰\s*평가|"
    r"자기\s*평가|동료\s*평가|개별\s*수행|모둠\s*수행|"
    r"원점수\s*\(\s*합산\s*\)|평균점|최고점|환산점|"
    r"포트폴리오|프로젝트|선택형|서술형|논술형|논술|보고서|발표|토론|실습|에세이|기타|교사)"
)
CHECKED_METHOD_RE = re.compile(
    r"(?:gfedcb|[■☑✅✓✔þ▣☒●])[\s\uF000-\uF8FF]*(" + METHOD_TERM_RE + r")",
    re.I,
)
CHECKED_CUSTOM_METHOD_RE = re.compile(
    r"(?:gfedcb|[■☑✅✓✔þ▣☒●])[\s\uF000-\uF8FF]*"
    r"([^□☐○■☑✅✓✔þ▣☒●]{2,80}?)(?=(?:gfedc|[□☐○■☑✅✓✔þ▣☒●])|$)",
    re.I,
)
TIMING_VALUE_RE = re.compile(
    r"(?:\d{1,2}\s*월(?:\s*\d{1,2}\s*주)?"
    r"(?:\s*[~∼～\-]\s*(?:\d{1,2}\s*월\s*)?\d{1,2}\s*주)?|"
    r"\d{1,2}\s*차시|수시|상시|학기\s*(?:중|말)|단원\s*(?:종료|말))"
)
SCORE_VALUE_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*점")
WEIGHT_VALUE_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")


def _collapse_adjacent_cells(row: list[str]) -> list[str]:
    """Collapse rowspan/colspan repetitions emitted by the table expander."""

    output: list[str] = []
    last_key = ""
    for cell in row:
        # ``_source_tables`` has already converted HTML cells to visible text.
        # Running the generic HTML stripper again would erase source-authored
        # angle-bracket text such as ``<직무수학>``.
        value = re.sub(r"\s+", " ", str(cell)).strip(" |")
        key = compact_text(value)
        if not key:
            continue
        if key == last_key:
            continue
        output.append(value)
        last_key = key
    return output


def _selected_methods(value: str) -> list[str]:
    output: list[str] = []
    for match in CHECKED_METHOD_RE.finditer(value):
        term = re.sub(METHOD_SEPARATOR_RE, "·", match.group(1))
        term = re.sub(r"\s*·\s*", "·", term)
        term = re.sub(r"\s+", " ", term).strip()
        output.append(term)
    if not output:
        for match in CHECKED_CUSTOM_METHOD_RE.finditer(value):
            term = re.sub(r"[\uF000-\uF8FF]", "", match.group(1))
            term = re.sub(r"\s+", " ", term).strip(" |:：")
            if term and compact_text(term) not in METHOD_SUBLABELS:
                output.append(term)
    return _unique_values(output, 12)


def _first_pattern(values: list[str], pattern: re.Pattern[str]) -> str:
    for value in values:
        match = pattern.search(value)
        if match:
            clean = re.sub(r"\s+", " ", match.group(0)).strip()
            return re.sub(r"(?<=\d)\s+(?=(?:%|점|월|주))", "", clean)
    return ""


def _first_value_after_label(
    values: list[str],
    labels: tuple[str, ...],
    *,
    maximum_length: int,
) -> str:
    wanted = set(labels)
    keys = [compact_text(value) for value in values]
    for index, key in enumerate(keys):
        if key not in wanted:
            continue
        for candidate, candidate_key in zip(values[index + 1 :], keys[index + 1 :]):
            if candidate_key in ALL_FIELD_LABELS or any(
                candidate_key in aliases for aliases in FIELD_LABELS.values()
            ):
                break
            clean = re.sub(r"\s+", " ", candidate).strip(" |")
            if clean and len(clean) <= maximum_length:
                return clean
    return ""


def _exact_fields(segment: str) -> dict[str, object]:
    """Extract only source-labelled, field-shaped values from one item segment.

    Expanded HTML tables repeat cells for rowspans and colspans.  The former
    implementation appended every repeated neighbour and could consequently
    publish a rubric paragraph as a score or a column heading as a method.  We
    now collapse those repetitions and apply a field-specific shape check.
    Unclear values remain blank; the lossless source table is still displayed.
    """

    found: dict[str, list[str]] = {key: [] for key in FIELD_LABELS}
    tables = _source_tables(segment)
    for rows in tables:
        if _instruction_schedule_rows(rows):
            continue
        collapsed_rows = [_collapse_adjacent_cells(row) for row in rows]
        for row_index, values in enumerate(collapsed_rows):
            keys = [compact_text(value) for value in values]
            joined = " · ".join(values)

            if any(key in FIELD_LABELS["overview"] for key in keys):
                overview = _first_value_after_label(
                    values, FIELD_LABELS["overview"], maximum_length=500
                )
                if overview:
                    found["overview"].append(overview)

            if any(key in FIELD_LABELS["method"] for key in keys):
                selected = _selected_methods(joined)
                if selected:
                    found["method"].extend(selected)
                else:
                    # A plain label/value row (without checkboxes) is safe only
                    # when the value itself names a recognised method.
                    candidate = _first_value_after_label(
                        values, FIELD_LABELS["method"], maximum_length=120
                    )
                    if candidate and not re.search(r"gfedc|[□○]", candidate, re.I):
                        found["method"].append(candidate)

            if any(key in FIELD_LABELS["timing"] for key in keys):
                timing = _first_pattern(values, TIMING_VALUE_RE)
                if timing:
                    found["timing"].append(timing)

            has_weight_label = any(key in FIELD_LABELS["weight"] for key in keys)
            has_score_label = any(key in FIELD_LABELS["score"] for key in keys)
            # Some HWP converters merge "만점" and "반영비율" into the cell
            # that also contains the timing value.  The label text remains
            # source-authored, so the numeric shapes can still be separated.
            merged_labels = compact_text(joined)
            has_weight_label = has_weight_label or "반영비율" in merged_labels
            has_score_label = has_score_label or "만점" in merged_labels
            if has_weight_label:
                weight = _first_pattern(values, WEIGHT_VALUE_RE)
                if weight:
                    found["weight"].append(weight)
            if has_score_label:
                score = _first_pattern(values, SCORE_VALUE_RE)
                if score:
                    found["score"].append(score)

            # Rubric layouts often encode the total only as
            # "평가 영역(만점) | ..." followed by "과제명(35점)".
            if any("평가영역" in key and "만점" in key for key in keys):
                for following in collapsed_rows[row_index + 1 : row_index + 4]:
                    score = _first_pattern(following[:2], SCORE_VALUE_RE)
                    if score:
                        found["score"].append(score)
                        break

            # A compact PDF/Markdown summary table uses a pure header row and
            # puts each value in the same column on the following row. Keep
            # the original column positions here; collapsed rows intentionally
            # discard blank colspan placeholders.
            raw_values = [re.sub(r"\s+", " ", str(cell)).strip(" |") for cell in rows[row_index]]
            raw_keys = [compact_text(value) for value in raw_values]
            field_aliases = {alias for aliases in FIELD_LABELS.values() for alias in aliases}
            nonempty_raw_keys = [value for value in raw_keys if value]
            pure_field_header = (
                len({value for value in nonempty_raw_keys if value in field_aliases}) >= 2
                and all(value in field_aliases for value in nonempty_raw_keys)
            )
            if not pure_field_header:
                continue
            for key, aliases in FIELD_LABELS.items():
                for column_index, label in enumerate(raw_keys):
                    if label not in aliases:
                        continue
                    vertical = ""
                    for following in rows[row_index + 1 :]:
                        if column_index >= len(following):
                            continue
                        candidate = re.sub(r"\s+", " ", str(following[column_index])).strip(" |")
                        candidate_key = compact_text(candidate)
                        if not candidate or candidate_key in ALL_FIELD_LABELS:
                            continue
                        vertical = candidate
                        break
                    if not vertical:
                        continue
                    if key == "timing":
                        value = _first_pattern([vertical], TIMING_VALUE_RE)
                    elif key == "weight":
                        value = _first_pattern([vertical], WEIGHT_VALUE_RE)
                    elif key == "score":
                        value = _first_pattern([vertical], SCORE_VALUE_RE)
                    elif key == "method":
                        selected = _selected_methods(vertical)
                        value = " · ".join(selected) if selected else vertical[:120]
                    else:
                        value = vertical[:500]
                    if value:
                        found[key].append(value)

    standards = _unique_values(
        re.findall(r"\[(?:10|12)[^\]\s]{2,24}\]", visible_text(segment)), 24
    )
    unique_overview = _unique_values(found["overview"], 2)
    unique_methods = [
        value for value in _unique_values(found["method"], 16)
        if compact_text(value) not in METHOD_SUBLABELS
        and not re.search(r"gfedc|[□☐○■☑✅✓✔þ▣☒●]", value, re.I)
    ]
    recognised_method_keys = {compact_text(value) for value in METHOD_TERMS}
    recognised_methods = [
        value for value in unique_methods if compact_text(value) in recognised_method_keys
    ]
    method = " · ".join(recognised_methods[:12]) if recognised_methods else (
        unique_methods[0][:160] if unique_methods else ""
    )

    # More than one distinct numeric or timing candidate in a single item is
    # ambiguous (often an area total next to rubric thresholds).  Do not guess
    # which one the teacher intended; the complete source table remains below.
    unambiguous: dict[str, str] = {}
    for key in ("timing", "score", "weight"):
        values = _unique_values(found[key], 5)
        unambiguous[key] = values[0] if len(values) == 1 else ""

    return {
        "overview": " · ".join(unique_overview),
        "method": method,
        **unambiguous,
        "standards": standards,
    }


class _SafeTableParser(StdlibHTMLParser):
    allowed_tags = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "br", "caption"}
    allowed_attrs = {"rowspan", "colspan"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.allowed_tags:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            if name.lower() not in self.allowed_attrs or value is None:
                continue
            if value.isdigit() and 1 <= int(value) <= 50:
                safe_attrs.append(f' {name.lower()}="{int(value)}"')
        self.output.append(f"<{tag}{''.join(safe_attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.output.append("<br>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.allowed_tags and tag != "br":
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data))


def sanitize_table_html(value: str) -> str:
    parser = _SafeTableParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def _split_pipe_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_fragment_to_html(markdown: str) -> str:
    """Render the parser's restricted Markdown/HTML subset to safe HTML."""

    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"<table\b", line, flags=re.I):
            chunk: list[str] = []
            depth = 0
            while index < len(lines):
                current = lines[index]
                chunk.append(current)
                depth += len(re.findall(r"<table\b", current, flags=re.I))
                depth -= len(re.findall(r"</table>", current, flags=re.I))
                index += 1
                if depth <= 0:
                    break
            output.append(sanitize_table_html("\n".join(chunk)))
            continue
        if (
            line.strip().startswith("|")
            and index + 1 < len(lines)
            and PIPE_SEPARATOR_RE.fullmatch(lines[index + 1])
        ):
            headers = _split_pipe_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_pipe_row(lines[index]))
                index += 1
            header_html = "".join(f"<th>{_inline_html(cell)}</th>" for cell in headers)
            output.append(f"<table><thead><tr>{header_html}</tr></thead><tbody>")
            for row in rows:
                row_html = "".join(f"<td>{_inline_html(cell)}</td>" for cell in row)
                output.append(f"<tr>{row_html}</tr>")
            output.append("</tbody></table>")
            continue
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = min(6, len(heading.group(1)) + 1)
            output.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
        elif re.match(r"^[-*•▪]\s+", stripped):
            list_text = re.sub(r"^[-*•▪]\s+", "", stripped)
            output.append(f'<p class="source-list-item">• {_inline_html(list_text)}</p>')
        else:
            output.append(f"<p>{_inline_html(stripped)}</p>")
        index += 1
    return balance_table_tags("\n".join(output))


def balance_table_tags(value: str) -> str:
    """Close extractor-truncated table tags without changing source text."""

    opening = len(re.findall(r"<table\b", value, flags=re.I))
    closing = len(re.findall(r"</table>", value, flags=re.I))
    if opening > closing:
        return value + ("\n</table>" * (opening - closing))
    return value


def _inline_html(value: str) -> str:
    escaped = html.escape(html.unescape(value))
    escaped = re.sub(r"&lt;br\s*/?&gt;", "<br>", escaped, flags=re.I)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _rubric_html(segment: str) -> str:
    tables: list[str] = []
    for match in re.finditer(r"<table\b.*?</table>", segment, flags=re.I | re.S):
        shown = visible_text(match.group(0))
        if re.search(r"채점\s*기준|세부\s*기준|평가\s*요소|평가\s*관점\s*및\s*배점\s*기준", shown) and re.search(
            r"점수|배점|부여\s*점수", shown
        ):
            tables.append(sanitize_table_html(match.group(0)))
    for fragment in _markdown_pipe_table_fragments(segment):
        shown = visible_text(fragment)
        if re.search(r"채점\s*기준|세부\s*기준|평가\s*요소|평가\s*관점\s*및\s*배점\s*기준", shown) and re.search(
            r"점수|배점|부여\s*점수|척도", shown
        ):
            tables.append(markdown_fragment_to_html(fragment))
    return balance_table_tags("\n".join(tables))


def parse_assessment_section(
    full_text: str,
    subject: str,
    title_hints: tuple[str, ...] = (),
) -> ParsedAssessmentSection:
    if any(marker in full_text for marker in CONTEXT_JUMP_MARKERS):
        raise ValueError("full source text contains a context-jump marker")
    subject_markdown, subject_start, _, subject_status = subject_local_markdown(full_text, subject)
    block, block_start, block_end, block_status = assessment_block(subject_markdown)
    headings = _heading_candidates(block)
    plan_titles = _plan_titles(subject_markdown)
    table_items = (
        _summary_table_items(
            block,
            subject,
            subject_status,
            subject_start + block_start,
        )
        if block_status == "assessment_anchor"
        else []
    )
    local_table_items = _explicit_local_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
    )
    matrix_items = _matrix_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
    )
    hinted_items = _hinted_table_items(
        subject_markdown,
        subject,
        subject_status,
        subject_start,
        title_hints,
    )
    allow_bounded_items = bool(
        headings
        and len(headings) <= MAX_BOUNDED_ITEMS
        and subject_status != "subject_heading_not_found"
        and block_status == "assessment_anchor"
    )
    items: list[ParsedAssessmentItem] = []
    if allow_bounded_items:
        for order, (_, start, title, title_raw) in enumerate(headings, 1):
            end = headings[order][1] if order < len(headings) else len(block)
            segment = block[start:end].strip()
            structural_heading = heading_title_is_structural(title)
            subject_alignment = segment_subject_alignment(segment, subject)
            subject_boundary_reliable = not (
                subject_alignment == "other"
                or (subject_status == "subject_mention_only" and subject_alignment == "unknown")
            )
            # An explicit source-table label outranks every numbered heading,
            # not only headings already classified as structural.  School
            # plans often number a generic subsection and put the real task
            # name in the first table row.
            table_title = explicit_segment_title(segment)
            table_display_title = (
                _clean_heading_title(table_title)[0] if table_title else ""
            )
            reliable_title = (
                bool(table_title) or not structural_heading
            ) and subject_boundary_reliable
            resolved_title = (
                table_display_title or title
                if reliable_title
                else "수행평가 원문 구간"
            )
            resolved_title_raw = table_title or title_raw if reliable_title else resolved_title
            resolved_title_basis = "table" if table_title else "heading"
            extraction_status = (
                "bounded"
                if reliable_title
                else "source_mismatch_review"
                if subject_alignment == "other"
                else "bundle_review"
            )
            fields = (
                _exact_fields(segment)
                if reliable_title
                else {
                    "overview": "",
                    "method": "",
                    "timing": "",
                    "score": "",
                    "weight": "",
                    "standards": [],
                }
            )
            items.append(
                ParsedAssessmentItem(
                    order=order,
                    title=resolved_title,
                    title_raw=resolved_title_raw,
                    title_basis=(resolved_title_basis if reliable_title else "unbounded_bundle"),
                    extraction_status=extraction_status,
                    source_start=subject_start + block_start + start,
                    source_end=subject_start + block_start + end,
                    source_markdown=segment,
                    source_html=markdown_fragment_to_html(segment),
                    rubric_html=_rubric_html(segment),
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(value) for value in fields["standards"]),
                )
            )
        existing_titles = {
            compact_text(item.title)
            for item in items
            if item.extraction_status == "bounded"
        }
        items.extend(
            item for item in table_items if compact_text(item.title) not in existing_titles
        )
        existing_titles.update(compact_text(item.title) for item in table_items)
        items.extend(
            item for item in local_table_items if compact_text(item.title) not in existing_titles
        )
        existing_titles.update(compact_text(item.title) for item in local_table_items)
        items.extend(
            item for item in matrix_items if compact_text(item.title) not in existing_titles
        )
        existing_titles.update(compact_text(item.title) for item in matrix_items)
        items.extend(
            item for item in hinted_items if compact_text(item.title) not in existing_titles
        )
        if not any(item.extraction_status == "bounded" for item in items):
            global_table_items = _expected_code_table_items(full_text, subject)
            items.extend(
                item
                for item in global_table_items
                if compact_text(item.title) not in existing_titles
            )
    elif table_items or local_table_items or matrix_items or hinted_items:
        for item in [*table_items, *local_table_items, *matrix_items, *hinted_items]:
            if compact_text(item.title) not in {
                compact_text(existing.title) for existing in items
            }:
                items.append(item)
    else:
        global_table_items = _expected_code_table_items(full_text, subject)
        if global_table_items:
            items.extend(global_table_items)
        else:
            # Preserve the whole section when the source does not expose safe item
            # boundaries.  Multiple plan-table titles stay visible as one bundle;
            # duplicating the same rubric under guessed titles would be misleading.
            single_table_title = (
                plan_titles[0]
                if len(plan_titles) == 1 and subject_status != "subject_heading_not_found"
                else ""
            )
            title = single_table_title or "수행평가 원문 구간"
            fields = (
                _exact_fields(block)
                if single_table_title
                else {
                    "overview": "",
                    "method": "",
                    "timing": "",
                    "score": "",
                    "weight": "",
                    "standards": [],
                }
            )
            items.append(
                ParsedAssessmentItem(
                    order=1,
                    title=title,
                    title_raw=title,
                    title_basis="table_bundle" if single_table_title else "unbounded_bundle",
                    extraction_status="bundle_review",
                    source_start=subject_start + block_start,
                    source_end=subject_start + block_end,
                    source_markdown=block,
                    source_html=markdown_fragment_to_html(block),
                    rubric_html=_rubric_html(block),
                    overview=str(fields["overview"]),
                    method=str(fields["method"]),
                    timing=str(fields["timing"]),
                    score=str(fields["score"]),
                    weight=str(fields["weight"]),
                    standards=tuple(str(value) for value in fields["standards"]),
                )
            )
    items = [replace(item, order=order) for order, item in enumerate(items, 1)]
    detected_titles: list[str] = []
    for item in items:
        if item.extraction_status == "bounded" and item.title not in detected_titles:
            detected_titles.append(item.title)
    return ParsedAssessmentSection(
        subject=subject,
        boundary_status=f"{subject_status}:{block_status}",
        source_start=subject_start + block_start,
        source_end=subject_start + block_end,
        source_markdown=block,
        detected_titles=tuple(detected_titles),
        items=tuple(items),
    )
