"""Build the course-scoped comparison registry from preserved MOE curriculum text.

2022 input is Kordoc's complete HWP Markdown (including table cells).
2015 input is PyMuPDF's sorted PDF text plus the AI course added by notice
2020-236 (preserved HWP paragraph text). Seven older PDF math glyph spans were
checked against the source PDF and transcribed as TeX; source files stay unchanged.
"""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data/derived/math_standard_comparison_20261107"
APP = ROOT / "services/math-assessment-api/app"
COURSES = {
    "2015": {
        "10수학": ("수학", 41),
        "12수학Ⅰ": ("수학Ⅰ", 19),
        "12수학Ⅱ": ("수학Ⅱ", 21),
        "12미적": ("미적분", 27),
        "12확통": ("확률과 통계", 17),
        "12기하": ("기하", 16),
        "12실수": ("실용 수학", 14),
        "12경수": ("경제 수학", 23),
        "12수과": ("수학과제 탐구", 8),
        "12인수": ("인공지능 수학", 13),
    },
    "2022": {
        "10공수1": ("공통수학1", 19),
        "10공수2": ("공통수학2", 20),
        "10기수1": ("기본수학1", 17),
        "10기수2": ("기본수학2", 17),
        "12대수": ("대수", 18),
        "12미적Ⅰ": ("미적분Ⅰ", 20),
        "12확통": ("확률과 통계", 16),
        "12미적Ⅱ": ("미적분Ⅱ", 23),
        "12기하": ("기하", 14),
        "12경수": ("경제 수학", 18),
        "12인수": ("인공지능 수학", 15),
        "12직수": ("직무 수학", 18),
        "12수문": ("수학과 문화", 16),
        "12실통": ("실용 통계", 13),
        "12수과": ("수학과제 탐구", 10),
    },
}
PDF_TRANSCRIPTIONS = {
    "10수학02-09": r"원점, $x$축, $y$축, 직선 $y=x$에 대한 대칭이동의 의미를 이해한다.",
    "10수학04-04": (
        r"유리함수 $y=\frac{ax+b}{cx+d}$의 그래프를 그릴 수 있고, "
        "그 그래프의 성질을 이해한다."
    ),
    "10수학04-05": (
        r"무리함수 $y=\sqrt{ax+b}+c$의 그래프를 그릴 수 있고, "
        "그 그래프의 성질을 이해한다."
    ),
    "12수학Ⅰ03-02": r"등차수열의 뜻을 알고, 일반항, 첫째항부터 제$n$항까지의 합을 구할 수 있다.",
    "12수학Ⅰ03-03": r"등비수열의 뜻을 알고, 일반항, 첫째항부터 제$n$항까지의 합을 구할 수 있다.",
    "12수학Ⅰ03-05": r"여러 가지 수열의 첫째항부터 제$n$항까지의 합을 구할 수 있다.",
    "12수학Ⅱ02-04": r"함수 $y=x^n$($n$은 양의 정수)의 도함수를 구할 수 있다.",
}


def entries(curriculum: str) -> list[dict[str, str]]:
    names = (
        ["math-curriculum.md"]
        if curriculum == "2022"
        else ["math-curriculum-2015.txt", "math-curriculum-2015-ai.txt"]
    )
    lines = "\n".join((DERIVED / name).read_text("utf-8") for name in names)
    lines = lines.replace("\x01", " ").splitlines()
    result = []
    for index, line in enumerate(lines):
        match = re.match(r"^\[((?:10|12)[^\]]+)\]\s+(.+)", line.strip())
        if not match:
            continue
        code = re.sub(r"\s+", "", match[1])
        prefix = re.sub(r"-?\d{2}-\d{2}$", "", code)
        if prefix not in COURSES[curriculum]:
            continue
        text = match[2].strip()
        if curriculum == "2015":
            for following in lines[index + 1 : index + 7]:
                if text.endswith("다.") or following.strip().startswith(("[", "(가)", "(나)")):
                    break
                text += " " + following.strip()
            text = " ".join(text.split())
            text = PDF_TRANSCRIPTIONS.get(code, text)
        assert text.endswith("다."), (code, text)
        assert not any(unicodedata.category(char) == "Co" for char in text), (code, text)
        result.append(
            {
                "key": unicodedata.normalize("NFKC", code),
                "code": f"[{code}]",
                "curriculum": curriculum,
                "subject": COURSES[curriculum][prefix][0],
                "text": text,
            }
        )
    assert len({entry["key"] for entry in result}) == len(result)
    for subject, expected in COURSES[curriculum].values():
        assert sum(entry["subject"] == subject for entry in result) == expected, subject
    return result


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> None:
    sources = {
        "2015": (
            "data/raw/official_curriculum/moe-2015-74/math-curriculum.pdf",
            "https://www.moe.go.kr/boardCnts/view.do?boardID=141&boardSeq=60747&lev=0&m=040401&opType=N&page=22&s=moe&searchType=null&statusYN=W",
            "2015-74",
        ),
        "2022": (
            "data/raw/moe-2022-33/extracted/books-05-14/[별책8] 수학과 교육과정.hwp",
            "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=141&boardSeq=93458&lev=0&m=0302",
            "2022-33",
        ),
    }
    for curriculum, (source, url, notice) in sources.items():
        standards = entries(curriculum)
        registry = {
            "curriculum": curriculum,
            "subjects": [value[0] for value in COURSES[curriculum].values()],
            "source_url": url,
            "source_title": f"교육부 고시 제{notice}호 별책 8 수학과 교육과정",
            "source_sha256": hashlib.sha256((ROOT / source).read_bytes()).hexdigest(),
            "standards": standards,
        }
        if curriculum == "2015":
            ai_source = ROOT / "data/raw/official_curriculum/moe-2020-236/math-curriculum.hwp"
            registry["subject_sources"] = {
                "인공지능 수학": {
                    "source_url": "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=141&boardSeq=81884&lev=0",
                    "source_title": "교육부 고시 제2020-236호 별책 8 수학과 교육과정",
                    "source_sha256": hashlib.sha256(ai_source.read_bytes()).hexdigest(),
                }
            }
        write_json(APP / f"math_standards_{curriculum}.json", registry)
    write_json(
        ROOT / "apps/math-assessment-web/app/lib/math-courses.json",
        {
            curriculum: [value[0] for value in subjects.values()]
            for curriculum, subjects in COURSES.items()
        },
    )
    write_json(
        DERIVED / "all-subjects/registry-build.json",
        {
            "total_standards": sum(
                count for courses in COURSES.values() for _, count in courses.values()
            ),
            "curriculum_courses": sum(len(courses) for courses in COURSES.values()),
            "counts": {
                year: {subject: count for subject, count in courses.values()}
                for year, courses in COURSES.items()
            },
            "pdf_math_transcriptions": PDF_TRANSCRIPTIONS,
        },
    )


if __name__ == "__main__":
    main()
