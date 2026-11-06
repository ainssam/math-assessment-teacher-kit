"""Run a conservative, case-by-case audit of published assessment titles.

This audit is intentionally stricter than the public catalog builder.  It does
not claim that a title is wrong merely because it is generic; instead it
separates obvious extraction failures, low-confidence candidates, and titles
that are supported by a table or heading in the original extracted evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.math_assessment_detail_parser import heading_title_is_structural

PLACEHOLDERS = {
    "구체적 과제명 미탐지",
    "수행평가 원문 구간",
    "수행평가명 미확정 · 원문 묶음",
}
LABEL_ONLY_RE = re.compile(
    r"^(?:평가영역|평가내용|평가 내용|성취기준|평가기준|평가종류|수행과제|"
    r"과목명|단원명|구분\(영역\)|점검 사항|선택형|서술형|구술[·・]발표)$"
)
SCORE_ONLY_RE = re.compile(r"^\d+(?:\.\d+)?\s*(?:점|%)$")
BOILERPLATE_RE = re.compile(
    r"평가\s*결과.*분석|정기시험|문항.*출제|학업성적관리|교수.?학습.*평가.*계획|"
    r"평가.*(?:목적|방침|원칙)|성취율|평가 문항을 출제|각 평가 기준의|"
    r"학교교육과정의 범위|수학과의 평가|학생 개개인"
)
RUBRIC_SENTENCE_RE = re.compile(
    r"(?:함|한다|된다|있다|않음|미흡|옳음|틀림)[.!]?$|"
    r"(?:완성도|정확성|충실도|적합성|태도|부분적)$"
)
RUBRIC_SCORE_RE = re.compile(
    r"미제출|미작성|무응답|총점\s*\(|"
    r"(?:작성|해결|제출|풀이|완성도|소감|필기).*(?:미만|이상|\d+\s*%|맞음)|"
    r"(?:한|못한|된|있는|없는|일|인)\s*경우$|"
    r"\d+\s*(?:자|개|가지|번|회|%)?\s*(?:이상|미만)|"
    r"제출함|작성하였으나|부분적으로|찾지 못|수행하였는가|양식에$"
)
TASK_SIGNAL_RE = re.compile(
    r"탐구|프로젝트|보고서|포트폴리오|발표|토론|모델링|문제|문항|제작|"
    r"만들기|작성|분석|설명서|수학\s*일지|학습\s*일지|배움\s*노트|오답|"
    r"독서|논술|인포그래픽|시각화|증명|설계|글쓰기|기사|마인드맵|읽|말하기|그리기|"
    r"문제\s*풀이|표현하기|해석|계산하기|정리하기|활동|쓰기|찾기|알아보기|"
    r"기르기|키우기|작도|구성하기|개발|구현|서술하기|활용하기|배치하기|"
    r"디자인하기|연구|조사|독후감|서평|칼럼|북마케터|써클맵|도서|공유|"
    r"예측|기록|설명하기|구조화하기|해결하기|구하기|완성하기|파악하기|"
    r"의사소통하기|추론하기|적용하기|이해하기|세우기|분류하기|탐색하기|"
    r"연결하기|나타내기|처리하기|사고하기|짓기|평가하기|수용하기|"
    r"도출하기|검증하기|성찰하기|수립하기|요약하기|수행하기|기술하기|"
    r"확장하기|추측하기|맞추기|인출하기|해독하기|찾아보기|모색하기|"
    r"상기하기|실천하기|일지|노트|퀴즈|사전|디자인|스크랩|아카이빙|"
    r"플래너|큐레이션|프레젠테이션|씽킹맵|워크북|신문|프로그램|콘테스트|비평"
)
RUBRIC_TITLE_TERMS = (
    "미참여",
    "미응시",
    "백지",
    "장기 결석",
    "장기결석",
    "전입생",
    "편입생",
    "인정점",
    "득점",
    "감점",
    "점 부여",
    "제출자",
    "작성하였",
    "하지 못",
    "못함",
    "미흡",
    "부분적",
    "충실",
    "완성도",
    "수 있음",
    "수 있다",
    "수 없다",
    "점수 있음",
    "평가 시기는",
    "변경될 수 있음",
    "부족함",
    "역량 평가",
    "능력 신장",
    "분량",
    "성실히",
    "올바른 표현",
    "논리에 어긋나지",
)
TASK_END_RE = re.compile(r"(?:만들기|작성하기|탐구하기|보고서|프로젝트)$")
NUMERIC_SCORE_RE = re.compile(r"[0-9\s~.,+×xX%점]+")
SCORE_METADATA_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:점|%)|\d+\s*학점|"
    r"반영\s*(?:만점|비율)|만점\s*\(?비율\)?|배점|점수\s*부여|"
    r"분할\s*점수|운영\s*시수|학점\s*당|서답형|선택형"
)
FIELD_OR_POLICY_RE = re.compile(
    r"^(?:평가|채점|성취|교과|핵심|관련|수행평가|학습|교육과정|내용|운영|"
    r"실시|시행|동점자|성적|결과물|기본|기타|학생|AI\s*활용|수업|교과)"
    r".*(?:항목|요소|기준|수준|범위|단원|역량|과제명|평가명|유의\s*사항|"
    r"주체|방향|방식|방법|점수|시기|횟수|우선\s*순위|처리|계획|사항|"
    r"개요|기록|보존|규정|평가)$"
)
EXAM_OR_FIELD_RE = re.compile(
    r"^(?:(?:1|2)\s*차\s*)?(?:중간|기말)?\s*(?:시험|고사)(?:\s*\([^)]*\))?$|"
    r"^(?:1|2)\s*회\s*(?:시험|고사)(?:\s*\([^)]*\))?$|"
    r"^(?:구\s*분|합\s*계|내\s*용|배\s*점|시\s*기|관련\s*단원|관련\s*대단원|"
    r"평가\s*항목|평가\s*범위|평가\s*점수|채점\s*요소|유의\s*사항|"
    r"학생\s*유의\s*사항|수행평가명|평가과제명|과제명|평가명)$"
)
FIELD_VALUE_FRAGMENT_RE = re.compile(
    r"^(?:평소|단원|수준|학습|직무|그\s*외|수학과|수행평가|"
    r"점수\s*\(\s*점\s*\)|평가만점|공통수학[12]\s*전체|"
    r"(?:정기\s*)?\d+\s*차\s*시험|중간|기말|[IVⅠⅡⅢⅣ]+)$"
)
TEMPLATE_POLICY_RE = re.compile(
    r"성취기준에 기반한 일관성 있는 평가|과정 중심 평가 및 피드백|"
    r"자기주도 학습 지원|교육 목표 도달 확인|전인적 성장 도모"
)
GENERIC_RUBRIC_CELL_RE = re.compile(
    r"^(?:평가\s*기준\s*\d+개(?:\s*이하)?\s*충족|개념\s*이해\s*및\s*적용(?:이\s*부족함)?|"
    r"(?:학습|탐구|수학)?\s*내용\s*정리|활동지|수업\s*참여|자료\s*조사|"
    r"탐구\s*주제\s*선정\s*및\s*계획|실제\s*문제\s*해결\s*역량\s*평가)$"
)
METHOD_OR_GENERIC_ACTIVITY_RE = re.compile(
    r"^(?:서.?논술형\s*평가\d*|논술형\s*평가|구술\s*평가|사고력\s*평가|"
    r"역량\s*평가|수행\s*활동\s*과정|활동\s*내용|평가\s*시간\s*내에\s*완료하기|"
    r"수행\s*과제\d*\s*:\s*서.?논술형\s*평가\d*|서술.?논술|구술.?발표|"
    r"토의.?토론|조사.?관찰|실험.?실습|서.?논술|서술.?논술형|"
    r"보고서\s*및\s*발표|토론\s*및\s*발표|관찰평가\s*포트폴리오)$"
)
METHOD_ONLY_COMBINATION_RE = re.compile(
    r"^(?:서.?논술형?|서술.?논술|구술.?발표|토의.?토론|론.?토의|조사.?관찰|실험.?실습|"
    r"포트폴리오|프로젝트|발표|논술|서술|구술|토론)(?:\s*(?:[,·/]|및|\s)\s*"
    r"(?:서.?논술형?|서술.?논술|구술.?발표|토의.?토론|론.?토의|조사.?관찰|실험.?실습|"
    r"포트폴리오|프로젝트|발표|논술|서술|구술|토론))+$"
)
MULTI_STEP_LIST_RE = re.compile(
    r"(?:주제\s*선정|자료\s*수집|탐구\s*수행|결과물\s*제작)\s*,.*"
    r"(?:주제\s*선정|자료\s*수집|탐구\s*수행|결과물\s*제작)"
)
RUBRIC_QUESTION_RE = re.compile(
    r"(?:적절한가|충실한가|정확한가|타당한가|명확한가|활용하였는가|"
    r"사용하였는가|제시하였는가|작성하였는가|수행하였는가)\s*\?$"
)
RUBRIC_PAGE_THRESHOLD_RE = re.compile(
    r"(?:평가\s*항목|기준).*(?:\d+\s*[~～-]\s*\d+|\d+\s*(?:쪽|개|회|가지))"
)
SCORED_SUBCRITERION_RE = re.compile(
    r"(?:\d+\s*\(\s*점\s*\)|\(\s*(?:[5-9]|[1-9]\d|100)\s*(?:점)?\s*\))"
    r"\s*(?:\([^)]*\))?$"
)
RUBRIC_DIMENSION_RE = re.compile(
    r"^(?:탐구\s*(?:설계|수행|주제\s*선정)|주제\s*선정|"
    r"보고서\s*작성|발표|상황\s*분석(?:\s*및\s*수학\s*개념\s*선정)?|"
    r"분석\s*과정\s*및\s*해석|탐구\s*성실성\s*및\s*자기\s*사고|"
    r"탐구\s*과정\s*및\s*결과|활동지\s*(?:기반\s*)?(?:개념\s*이해|수행\s*성실성))"
    r"(?:\s*\(\s*\d+\s*(?:점)?\s*\))?$"
)
METHOD_LIST_RE = re.compile(
    r"^(?=.*교사\s*관찰)(?=.*(?:서.?논술|포트폴리오|조사.?발표|프로젝트))"
    r".*(?:,|·|및).*$"
)
OTHER_SUBJECT_RE = re.compile(
    r"국어|문학|화법|작문|언어와\s*매체|한국사|세계사|사회.?문화|윤리|"
    r"지리\s*탐구|영어|영미|한문|동사의\s*활용|생명과학|물리학|화학|"
    r"미술|음악|체육|기본권|사회문제"
)
MATH_CONTEXT_RE = re.compile(
    r"수학|함수|방정식|부등식|수열|미분|적분|확률|통계|기하|도형|벡터|"
    r"행렬|지수|로그|삼각|다항식|실수|복소수|집합|명제|경우의\s*수|"
    r"이차곡선|좌표|연산|모델링|데이터|수치|그래프"
)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_title_full_audit.json",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=root / "data" / "publish" / "math_assessment_title_review_queue.csv",
    )
    return parser.parse_args()


def audit_flags(title: str, basis: str) -> list[str]:
    flags: list[str] = []
    if not title or title in PLACEHOLDERS:
        return ["missing"]
    if LABEL_ONLY_RE.fullmatch(title):
        flags.append("label_as_title")
    if SCORE_ONLY_RE.fullmatch(title):
        flags.append("score_as_title")
    if BOILERPLATE_RE.search(title):
        flags.append("policy_or_exam_text")
    if heading_title_is_structural(title):
        flags.append("structural_or_policy_heading")
    if (
        "[...문맥 전환...]" in title
        or "<td" in title
        or "<tr" in title
        or re.search(r"gfedcb?|(?:(?:row|col|l)?span|pan)\s*=", title, re.I)
    ):
        flags.append("parser_artifact")
    if len(re.findall(r"[\u3400-\u9fff]", title)) >= 2:
        flags.append("encoding_artifact")
    if any(marker in title for marker in ("□", "◻", "☐", "☑", "■", "▸", "▶", "▪")):
        flags.append("list_or_checkbox_fragment")
    if len(title) > 48:
        flags.append("overlong_title")
    if RUBRIC_SENTENCE_RE.search(title) and len(title) > 24:
        flags.append("sentence_or_rubric")
    if RUBRIC_SCORE_RE.search(title):
        flags.append("rubric_score_text")
    if any(term in title for term in RUBRIC_TITLE_TERMS):
        flags.append("rubric_or_policy_candidate")
    if "경우" in title and "경우의 수" not in title:
        flags.append("conditional_rubric_candidate")
    if re.search(r"(?:이상|미만)", title) and not TASK_END_RE.search(title):
        flags.append("threshold_rubric_candidate")
    if NUMERIC_SCORE_RE.fullmatch(title):
        flags.append("numeric_score_candidate")
    if SCORE_METADATA_RE.search(title):
        flags.append("score_metadata_candidate")
    if FIELD_OR_POLICY_RE.search(title):
        flags.append("field_or_policy_candidate")
    if EXAM_OR_FIELD_RE.fullmatch(title):
        flags.append("exam_or_field_candidate")
    if FIELD_VALUE_FRAGMENT_RE.fullmatch(title):
        flags.append("field_value_fragment_candidate")
    if TEMPLATE_POLICY_RE.search(title):
        flags.append("template_policy_candidate")
    if GENERIC_RUBRIC_CELL_RE.fullmatch(title):
        flags.append("generic_rubric_cell_candidate")
    if METHOD_OR_GENERIC_ACTIVITY_RE.fullmatch(title):
        flags.append("method_or_generic_activity_candidate")
    if METHOD_ONLY_COMBINATION_RE.fullmatch(title):
        flags.append("method_combination_candidate")
    if re.search(r"평가\s*방법", title):
        flags.append("assessment_method_candidate")
    if re.search(r"(?:작성\s*내용|창의성|흥미도|이해도|연계성)$", title):
        flags.append("rubric_dimension_candidate")
    if re.search(r"(?:역량|능력\s*신장)$", title):
        flags.append("objective_candidate")
    if MULTI_STEP_LIST_RE.search(title):
        flags.append("multi_step_list_candidate")
    if RUBRIC_QUESTION_RE.search(title):
        flags.append("rubric_question_candidate")
    if RUBRIC_PAGE_THRESHOLD_RE.search(title):
        flags.append("rubric_page_threshold_candidate")
    if SCORED_SUBCRITERION_RE.search(title):
        flags.append("scored_subcriterion_candidate")
    if basis == "table" and RUBRIC_DIMENSION_RE.search(title):
        flags.append("rubric_dimension_phrase_candidate")
    if METHOD_LIST_RE.search(title):
        flags.append("method_list_candidate")
    if OTHER_SUBJECT_RE.search(title) and not MATH_CONTEXT_RE.search(title):
        flags.append("other_subject_without_math_candidate")
    if re.fullmatch(r"수학\s*과제\s*탐구", title):
        flags.append("generic_course_name_candidate")
    if re.search(r"수학\s*과제\s*탐구의\s*(?:이해|실행과\s*평가)", title):
        flags.append("generic_course_outline_candidate")
    if re.fullmatch(r"교수\s*학습\s*활동", title):
        flags.append("teaching_activity_heading_candidate")
    if (
        "창의적 사고와 문화 활동" in title
        or "사이버 어울림활동" in title
        or re.search(r"사회\s*현상의\s*이해와\s*탐구", title)
    ):
        flags.append("non_task_heading_candidate")
    if re.search(r"(?:확인한\s*)?총\s*횟수$", title):
        flags.append("count_rubric_candidate")
    if len(title) > 32 and re.search(r"(?:과|및|을|를|의)$", title):
        flags.append("truncated_sentence_candidate")
    if re.search(r"^평가\s*내용\s*및\s*평가\s*기준", title):
        flags.append("field_heading_candidate")
    if title.count("수업") >= 2:
        flags.append("teaching_method_row_candidate")
    if re.search(
        r"Character\s+Spotlight|영미소설|Supplementary\s+Reading|"
        r"Sculpt\s+Your\s+Dream|동사의\s*활용",
        title,
        re.I,
    ):
        flags.append("other_subject_candidate")
    if not TASK_SIGNAL_RE.search(title):
        flags.append("no_task_signal")
    if basis in {"context", "missing"}:
        flags.append("weak_source_basis")
    return flags


def confidence(
    flags: list[str],
    basis: str,
    *,
    explicit_source_label: bool = False,
) -> str:
    hard = {
        "label_as_title",
        "score_as_title",
        "policy_or_exam_text",
        "structural_or_policy_heading",
        "parser_artifact",
        "encoding_artifact",
        "list_or_checkbox_fragment",
        "sentence_or_rubric",
        "rubric_score_text",
        "rubric_or_policy_candidate",
        "conditional_rubric_candidate",
        "threshold_rubric_candidate",
        "numeric_score_candidate",
        "score_metadata_candidate",
        "field_or_policy_candidate",
        "exam_or_field_candidate",
        "field_value_fragment_candidate",
        "template_policy_candidate",
        "generic_rubric_cell_candidate",
        "method_or_generic_activity_candidate",
        "method_combination_candidate",
        "assessment_method_candidate",
        "rubric_dimension_candidate",
        "objective_candidate",
        "multi_step_list_candidate",
        "rubric_question_candidate",
        "rubric_page_threshold_candidate",
        "scored_subcriterion_candidate",
        "rubric_dimension_phrase_candidate",
        "method_list_candidate",
        "other_subject_without_math_candidate",
        "generic_course_name_candidate",
        "generic_course_outline_candidate",
        "teaching_activity_heading_candidate",
        "non_task_heading_candidate",
        "count_rubric_candidate",
        "truncated_sentence_candidate",
        "field_heading_candidate",
        "teaching_method_row_candidate",
        "other_subject_candidate",
    }
    if "missing" in flags:
        return "missing"
    if (
        explicit_source_label
        and basis == "table"
        and set(flags).issubset(
            {
                "no_task_signal",
                "overlong_title",
                "rubric_dimension_phrase_candidate",
            }
        )
    ):
        return "supported"
    if hard.intersection(flags):
        return "reject"
    # A school may use a short unit-like phrase as the official assessment
    # name (for example, "다항식").  The phrase alone is not enough to publish,
    # but an exact value from a dedicated 평가명/수행평가명/평가영역명 cell is
    # primary-source evidence.  Keep the distinction explicit so a generic
    # topic inferred from surrounding prose is still sent to review.
    if basis in {
        "table",
        "heading",
        "section",
        "source_detail",
        "source_detail_bundle_review_table_title",
    } and not {
        "overlong_title",
        "no_task_signal",
    }.intersection(flags):
        return "supported"
    return "review"


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT cases.case_id, cases.curriculum, cases.subject, cases.school_name,
               cases.primary_task_name, cases.task_names_json, cases.title_basis,
               cases.source_url, case_detail_status.extraction_status AS detail_status
        FROM cases
        JOIN case_detail_status ON case_detail_status.case_id = cases.case_id
        ORDER BY cases.curriculum, cases.subject, cases.school_name, cases.case_id
        """
    ).fetchall()
    bounded_title_evidence: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for evidence_row in connection.execute(
        """
        SELECT case_id, title, title_basis
        FROM assessment_items
        WHERE extraction_status = 'bounded'
        """
    ):
        title_key = re.sub(r"\s+", "", str(evidence_row["title"] or ""))
        if title_key:
            bounded_title_evidence[str(evidence_row["case_id"])][title_key].add(
                str(evidence_row["title_basis"] or "")
            )
    connection.close()

    status_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    subject_counts: dict[str, Counter[str]] = defaultdict(Counter)
    queue: list[dict[str, str]] = []
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    candidate_status_counts: Counter[str] = Counter()
    public_status_counts: Counter[str] = Counter()
    public_candidate_status_counts: Counter[str] = Counter()
    candidate_flag_counts: Counter[str] = Counter()
    candidate_samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    candidate_total = 0
    for row in rows:
        title = str(row["primary_task_name"] or "").strip()
        basis = str(row["title_basis"] or "")
        public_case = str(row["detail_status"]) == "bounded"
        primary_evidence_bases = bounded_title_evidence[str(row["case_id"])].get(
            re.sub(r"\s+", "", title),
            set(),
        )
        audit_basis = (
            "table"
            if "table" in primary_evidence_bases
            else next(iter(primary_evidence_bases), basis)
        )
        flags = audit_flags(title, audit_basis)
        status = confidence(
            flags,
            audit_basis,
            explicit_source_label="table" in primary_evidence_bases,
        )
        status_counts[status] += 1
        if public_case:
            public_status_counts[status] += 1
        subject_counts[f"{row['curriculum']}|{row['subject']}"][status] += 1
        for flag in flags:
            flag_counts[flag] += 1
            if len(samples[flag]) < 12:
                samples[flag].append(
                    {
                        "case_id": str(row["case_id"]),
                        "school_name": str(row["school_name"]),
                        "subject": str(row["subject"]),
                        "title": title,
                        "basis": basis,
                    }
                )
        if status != "supported":
            queue.append(
                {
                    "record_kind": "primary",
                    "status": status,
                    "flags": "|".join(flags),
                    "case_id": str(row["case_id"]),
                    "curriculum": str(row["curriculum"]),
                    "subject": str(row["subject"]),
                    "school_name": str(row["school_name"]),
                    "primary_task_name": title,
                    "candidate_title": "",
                    "candidate_index": "",
                    "title_basis": basis,
                    "detail_status": str(row["detail_status"]),
                    "source_url": str(row["source_url"]),
                }
            )

        try:
            candidate_names = json.loads(str(row["task_names_json"] or "[]"))
        except json.JSONDecodeError:
            candidate_names = []
            candidate_status_counts["reject"] += 1
            if public_case:
                public_candidate_status_counts["reject"] += 1
            candidate_flag_counts["malformed_task_names_json"] += 1
            queue.append(
                {
                    "record_kind": "candidate",
                    "status": "reject",
                    "flags": "malformed_task_names_json",
                    "case_id": str(row["case_id"]),
                    "curriculum": str(row["curriculum"]),
                    "subject": str(row["subject"]),
                    "school_name": str(row["school_name"]),
                    "primary_task_name": title,
                    "candidate_title": "",
                    "candidate_index": "",
                    "title_basis": basis,
                    "detail_status": str(row["detail_status"]),
                    "source_url": str(row["source_url"]),
                }
            )
        if not isinstance(candidate_names, list):
            candidate_names = []
        for candidate_index, raw_candidate in enumerate(candidate_names):
            candidate = str(raw_candidate or "").strip()
            candidate_total += 1
            candidate_evidence_bases = bounded_title_evidence[str(row["case_id"])].get(
                re.sub(r"\s+", "", candidate),
                set(),
            )
            candidate_audit_basis = (
                "table"
                if "table" in candidate_evidence_bases
                else next(iter(candidate_evidence_bases), basis)
            )
            candidate_flags = audit_flags(candidate, candidate_audit_basis)
            candidate_status = confidence(
                candidate_flags,
                candidate_audit_basis,
                explicit_source_label="table" in candidate_evidence_bases,
            )
            candidate_status_counts[candidate_status] += 1
            if public_case:
                public_candidate_status_counts[candidate_status] += 1
            for flag in candidate_flags:
                candidate_flag_counts[flag] += 1
                if len(candidate_samples[flag]) < 12:
                    candidate_samples[flag].append(
                        {
                            "case_id": str(row["case_id"]),
                            "school_name": str(row["school_name"]),
                            "subject": str(row["subject"]),
                            "title": candidate,
                            "basis": basis,
                        }
                    )
            if candidate_status == "reject":
                queue.append(
                    {
                        "record_kind": "candidate",
                        "status": candidate_status,
                        "flags": "|".join(candidate_flags),
                        "case_id": str(row["case_id"]),
                        "curriculum": str(row["curriculum"]),
                        "subject": str(row["subject"]),
                        "school_name": str(row["school_name"]),
                        "primary_task_name": title,
                        "candidate_title": candidate,
                        "candidate_index": str(candidate_index),
                        "title_basis": basis,
                        "detail_status": str(row["detail_status"]),
                        "source_url": str(row["source_url"]),
                    }
                )

    primary_hard_failures = public_status_counts["reject"]
    candidate_hard_failures = public_candidate_status_counts["reject"]

    summary = {
        "schema_version": 3,
        "cases": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "public_status_counts": dict(sorted(public_status_counts.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "candidate_total": candidate_total,
        "candidate_status_counts": dict(sorted(candidate_status_counts.items())),
        "public_candidate_status_counts": dict(
            sorted(public_candidate_status_counts.items())
        ),
        "candidate_flag_counts": dict(sorted(candidate_flag_counts.items())),
        "hard_failures": {
            "primary": primary_hard_failures,
            "candidate": candidate_hard_failures,
        },
        "passed": primary_hard_failures == 0 and candidate_hard_failures == 0,
        "review_queue_rows": len(queue),
        "subject_status_counts": {
            key: dict(sorted(value.items())) for key, value in sorted(subject_counts.items())
        },
        "samples": dict(sorted(samples.items())),
        "candidate_samples": dict(sorted(candidate_samples.items())),
        "interpretation": (
            "supported means the title is short, task-like, and backed by a table or heading. "
            "Review and missing titles remain in the manual queue but are not public. "
            "Only a rejected primary or candidate title in a bounded public case fails "
            "publication."
        ),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.summary.with_suffix(args.summary.suffix + ".partial")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.summary)

    args.queue.parent.mkdir(parents=True, exist_ok=True)
    temporary_queue = args.queue.with_suffix(args.queue.suffix + ".partial")
    with temporary_queue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(queue[0]) if queue else ["status"])
        writer.writeheader()
        writer.writerows(queue)
    os.replace(temporary_queue, args.queue)
    output_keys = (
        "cases",
        "status_counts",
        "public_status_counts",
        "candidate_total",
        "candidate_status_counts",
        "public_candidate_status_counts",
        "hard_failures",
        "passed",
        "review_queue_rows",
    )
    print(
        json.dumps(
            {key: summary[key] for key in output_keys},
            ensure_ascii=False,
        )
    )
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
