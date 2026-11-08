"""Conservative aliases for 2015/2022 Korean high-school math subjects."""

from __future__ import annotations

import html
import re
from functools import cache

SUBJECT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("2022", "공통수학1", r"공통\s*수학\s*(?:[1Ⅰ]|I(?!I))"),
    ("2022", "공통수학2", r"공통\s*수학\s*(?:[2Ⅱ]|II(?!I))"),
    ("2022", "기본수학1", r"기본\s*수학\s*(?:[1Ⅰ]|I(?!I))"),
    ("2022", "기본수학2", r"기본\s*수학\s*(?:[2Ⅱ]|II(?!I))"),
    ("2022", "미적분Ⅰ", r"미적분\s*(?:[1Ⅰ]|I(?!I))"),
    ("2022", "미적분Ⅱ", r"미적분\s*(?:[2Ⅱ]|II(?!I))"),
    ("2022", "실용 통계", r"실용\s*통계"),
    ("2022", "수학과 문화", r"수학\s*과\s*문화"),
    ("shared", "인공지능 수학", r"인공지능\s*수학"),
    ("2022", "직무 수학", r"직무\s*수학"),
    ("shared", "수학과제 탐구", r"수학\s*과제\s*탐구"),
    ("shared", "확률과 통계", r"확률\s*(?:과|[·ㆍ.])?\s*통계"),
    ("shared", "기하", r"(?<![가-힣])기하(?![가-힣])"),
    ("shared", "경제 수학", r"경제\s*수학"),
    ("2022", "대수", r"(?<![가-힣])대수(?![가-힣])"),
    ("2015", "수학Ⅰ", r"(?<!공통)(?<!공통 )(?<!기본)(?<!기본 )수학\s*(?:[1Ⅰ]|I(?!I))"),
    ("2015", "수학Ⅱ", r"(?<!공통)(?<!공통 )(?<!기본)(?<!기본 )수학\s*(?:[2Ⅱ]|II(?!I))"),
    ("2015", "미적분", r"미적분(?!\s*[1ⅠI2Ⅱ])"),
    ("2015", "실용 수학", r"실용\s*수학"),
    (
        "2015",
        "수학",
        r"(?m)^\s*(?:(?:[#*•·-]|\d+[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?)\s*)?(?:과목\s*명?\s*[:：]?\s*)?[<\[]?수학[>\]]?\s*$",
    ),
)


@cache
def semester_course_plan_pattern(subject_pattern: str) -> re.Pattern[str]:
    grade = r"(?:\(?[1-3]\)?\s*학년\s*)?"
    return re.compile(
        rf"20\d{{2}}\s*학년도\s*{grade}\(?[12]\)?\s*학기\s*{grade}"
        rf"[<\[(]?\s*(?:{subject_pattern.removeprefix('(?m)')})\s*[>\])]?\s*"
        r"(?:과목|교과|과)?\s*(?:교수\s*[·‧∙-]?\s*학습\s*[·‧∙-]?\s*(?:및\s*)?)?"
        r"평가\s*(?:운영\s*)?계획(?:서)?",
        re.IGNORECASE,
    )


def is_semester_course_plan_heading(line: str, subject_pattern: str) -> bool:
    if "학년도" not in line or "학기" not in line:
        return False
    visible = html.unescape(re.sub(r"</?[A-Za-z][^<>]*>", " ", line))
    return (
        semester_course_plan_pattern(subject_pattern).fullmatch(visible.strip(" #|\t")) is not None
    )


def subject_hits(text: str) -> list[dict[str, str]]:
    """Return de-duplicated subject hits with a small evidence window."""
    normalized = re.sub(r"[ \t]+", " ", text)
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for curriculum, subject, pattern in SUBJECT_PATTERNS:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            window = normalized[
                max(0, match.start() - 120) : min(len(normalized), match.end() + 120)
            ]
            # Subject labels, headings, or achievement-code rows are reliable;
            # ordinary mathematical prose is not.
            code_key = {
                "공통수학1": "공수1",
                "공통수학2": "공수2",
                "기본수학1": "기수1",
                "기본수학2": "기수2",
                "미적분Ⅰ": "미적Ⅰ",
                "미적분Ⅱ": "미적Ⅱ",
                "대수": "대수",
                "기하": "기하",
                "확률과 통계": "확통",
                "경제 수학": "경수",
                "실용 수학": "실수",
                "수학과제 탐구": "수과",
                "수학Ⅰ": "수학Ⅰ",
                "수학Ⅱ": "수학Ⅱ",
                "미적분": "미적분",
                "인공지능 수학": "인수",
                "직무 수학": "직수",
                "수학과 문화": "수문",
                "실용 통계": "실통",
            }.get(subject)
            line_start = normalized.rfind("\n", 0, match.start()) + 1
            line_end = normalized.find("\n", match.end())
            if line_end < 0:
                line_end = len(normalized)
            line = normalized[line_start:line_end]
            line_pattern = pattern.removeprefix("(?m)")
            code_hit = bool(code_key and re.search(rf"\[(?:10|12){re.escape(code_key)}", window))
            exact_line_hit = bool(
                re.fullmatch(
                    rf"\s*(?:[|│┃]\s*)?(?:(?:[#*•·-]|\d+[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?)\s*)?(?:(?:과목\s*명?|교과\s*목?)\s*[:：|]?\s*)?[<\[(]?\s*(?:{line_pattern})\s*[>\])]?(?:\s*[|│┃])?\s*",
                    line,
                    flags=re.IGNORECASE,
                )
            )
            previous_lines = normalized[max(0, line_start - 300) : line_start]
            label_hit = bool(
                re.search(r"과목\s*명?|교과\s*목?", line)
                or re.match(r"\s*#{1,6}\s*", line)
                or is_semester_course_plan_heading(line, line_pattern)
                or re.search(rf"[<\[(]\s*(?:{line_pattern})\s*[>\])]", line, flags=re.IGNORECASE)
                or ("|" in line and re.search(r"과목\s*명?|교과\s*목?", previous_lines))
            )
            if not code_hit and not label_hit and not exact_line_hit:
                continue
            key = f"{curriculum}:{subject}"
            if key in seen:
                break
            start = max(0, match.start() - 100)
            end = min(len(normalized), match.end() + 160)
            hits.append(
                {
                    "curriculum_hint": curriculum,
                    "subject": subject,
                    "evidence": normalized[start:end],
                }
            )
            seen.add(key)
            break

    # Bare ``수학`` is only accepted in a heading/subject-label context, not
    # from ordinary words such as ``교수학습`` or ``수학적``.
    bare = re.compile(
        r"(?m)^\s*(?:(?:[#*•·-]|\d+[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?)\s*)?(?:과목\s*명?\s*[:：]?\s*)?[<\[]?수학[>\]]?\s*$"
    )
    if "2015:수학" not in seen and bare.search(normalized):
        hits.append(
            {
                "curriculum_hint": "2015",
                "subject": "수학",
                "evidence": bare.search(normalized).group(0).strip(),
            }
        )
    return hits


def curriculum_from_codes(text: str) -> list[str]:
    codes = re.findall(
        r"\[(?:10|12)(공수[12]|기수[12]|미적[ⅠⅡ12]|대수|확통|기하|경수|인수|직수|수문|실통|수과|수학[ⅠⅡ12]|미적분|실수)-?\d{2}-\d{2}\]",
        text,
    )
    hints: set[str] = set()
    for code in codes:
        code = {"미적1": "미적Ⅰ", "미적2": "미적Ⅱ", "수학1": "수학Ⅰ", "수학2": "수학Ⅱ"}.get(
            code, code
        )
        if code in {"미적Ⅰ", "대수", "공수1", "공수2", "기수1", "기수2", "수문", "실통", "직수"}:
            hints.add("2022")
        elif code in {"수학Ⅰ", "수학Ⅱ", "미적분", "실수"}:
            hints.add("2015")
        elif code in {"확통", "기하", "경수", "수과", "인수"}:
            hints.update({"2015", "2022"})
    return sorted(hints)
