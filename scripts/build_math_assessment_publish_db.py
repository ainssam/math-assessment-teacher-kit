"""Build the privacy-conscious read-only database used by the teacher web app.

The source catalog contains long extracted document text and local paths.  This
builder deliberately publishes only normalized metadata, short evidence
excerpts, and public SCHOOLINFO disclosure-page URLs.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path

SCHEMA_VERSION = 3
MAX_EXCERPT_CHARS = 900
MAX_TASK_NAMES = 6
GENERIC_TASK_NAMES = {
    "기본 방향",
    "기본방향",
    "방침",
    "평가 방침",
    "평가 개요",
    "평가 계획",
    "평가 방법",
    "평가 목표",
    "수행평가",
    "수행평가 세부 계획",
    "기말고사",
    "중간고사",
    "탐구 학습",
    "토의·토론 학습",
    "수학적 모델링",
    "문제 만들기",
    "프로젝트",
    "보고서",
    "탐구 보고서",
    "보고서 작성 및 발표",
    "조사·발표",
    "발표",
    "포트폴리오",
    "정기시험",
    "피드백 및 기록",
    "교육과정 성취기준 및 평가기준",
    "과목명",
    "단원명",
    "구분(영역)",
    "성취기준",
    "선택형",
    "서술형",
    "수행과제",
    "평가결과 분석 및 활용",
    "평가결과분석및활용",
    "평가 결과 분석",
    "평가 결과 분석 및 활용",
    "평가 결과 분석 및 활용 방안",
    "평가 결과의 분석 및 활용",
    "평가 내용",
    "평가내용",
    "평가영역",
    "평가유형",
    "평가종류",
    "총정리",
    "점검 사항",
    "1학기",
    "교육과정성취기준",
    "교차채점 계획",
    "구술·발표",
    "구술・발표",
    "단답형",
    "반영 비율",
    "반영비율",
    "성취수준",
    "수행 평가",
    "수행평가 계획",
    "영역만점",
    "영역명",
    "일반사항",
    "일반 원칙",
    "정기 시험",
    "평가 영역",
    "평가 유형",
    "평가 종류",
    "평가 시기",
    "평가개요",
    "평가횟수",
    "평가기준",
    "2학기",
    "강의식 수업 발표, 토론",
    "기본점수",
    "배점(만점)",
    "성적 결과의 활용",
    "성적 산출",
    "성적 산출 방법",
    "수행평가 기준",
    "수행평가 분할점수",
    "수행평가 영역별 배점",
    "평가 과제",
    "미수행",
    "세부 평가 내용",
    "영역 만점",
    "운영 시기",
    "자료 보관 및 관리",
    "평가 기준",
    "정서지원 프로그램",
    "성취 기준",
    "일반원칙",
    "평가 시기(횟수)",
    "공통사항",
    "기타사항",
    "논술형",
    "동점자처리기준순위",
    "만 점",
    "만점점수",
    "서·논술형",
    "성취 기준 및 평가 기준",
    "수행 과제",
    "수행평가 운영",
    "역량 중심 평가",
    "영역 만점 (반영 비율)",
    "토의·토론",
    "평가 영역 및 반영 비율",
    "평가계획",
    "편입생",
    "학기말 반영 비율(%)",
    "기타 사항",
    "미응시자",
    "서논술형",
    "서‧논술형",
    "서술형 평가",
    "세부 계획",
    "이의 신청 기간",
    "교육과정 성취 기준",
    "교육과정 영역",
    "균형 있는 평가",
    "기본방침",
    "서술·논술형 평가",
    "성취기준 및 평가기준",
    "세부기준",
    "수행평가 척도안",
    "신체장애 학생의 인정점",
    "정의적 능력 평가 세부내용",
    "토의・토론",
    "평가 방법 및 내용",
    "평가 시 유의점",
    "평가척도",
    "학습과정평가",
    "횟수 /평가 영역",
    "수행평가 출제계획",
    "과제탐구",
    "과제 탐구",
}
EXCERPT_MARKERS = (
    "수행평가 세부 계획",
    "수행평가 영역별",
    "수행평가 계획",
    "평가 내용",
    "채점 기준",
    "평가기준",
)
HTML_ROW_RE = re.compile(r"</?(?:tr|p|li|h\d)(?:\s[^>]*)?>", re.IGNORECASE)
HTML_CELL_RE = re.compile(r"</?(?:td|th)(?:\s[^>]*)?>", re.IGNORECASE)
HTML_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
HTML_TABLE_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
HTML_TABLE_CELL_RE = re.compile(
    r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL
)
MARKDOWN_RULE_RE = re.compile(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?")
WHITESPACE_RE = re.compile(r"[\t\r\f\v ]+")
MULTILINE_RE = re.compile(r"\n{3,}")
MULTICELL_RE = re.compile(r"(?:\s*\|\s*){2,}")
TASK_SIGNAL_RE = re.compile(
    r"탐구|프로젝트|보고서|포트폴리오|발표|토론|모델링|문제|제작|만들기|"
    r"작성|분석|설명서|수학\s*일지|학습\s*일지|배움\s*노트|오답|독서|"
    r"캠페인|인포그래픽|시각화|증명|설계|글쓰기|기사|마인드맵|읽|말하기|"
    r"그리기|문제\s*풀이|표현하기|해석|계산하기|정리하기|논술|활동|쓰기|"
    r"찾기|알아보기|기르기|키우기|작도|구성하기|개발|구현|서술하기|"
    r"활용하기|배치하기|디자인하기|연구|조사|독후감|서평|칼럼|북마케터|"
    r"써클맵|도서|공유|예측|기록|설명하기|구조화하기|해결하기|구하기|"
    r"완성하기|파악하기|의사소통하기|추론하기|적용하기|이해하기|세우기|"
    r"분류하기|탐색하기|연결하기|나타내기|처리하기|사고하기|짓기|평가하기|"
    r"수용하기|도출하기|검증하기|성찰하기|수립하기|요약하기|수행하기|"
    r"기술하기|확장하기|추측하기|맞추기|인출하기|해독하기|찾아보기|"
    r"모색하기|상기하기|실천하기|일지|노트|퀴즈|사전|디자인|스크랩|"
    r"아카이빙|플래너|큐레이션|프레젠테이션|씽킹맵|워크북|신문|프로그램|"
    r"콘테스트|비평"
)
TASK_REJECT_RE = re.compile(
    r"평가의? (?:목적|방향|방침)|평가 유의|기본 방향|정기시험 및 수행평가|"
    r"교육과정 성취기준|교과학습 평가|수학과의 평가|성취율|학업성적관리|"
    r"학생 개개인|수학의 용어와 기호|사고 기능을 파악|전인적인 성장|"
    r"평가방법|평가 요소|평가요소|채점기준|채점 기준|기대 수행 수준|"
    r"교사 관찰|자기평가|동료평가|반영비율|평가시기"
    r"|수학적으로 .*하는 능력|관찰,? 분석,? 조직하는 능력|"
    r"(?:완성도|정확성|충실성|적절성|표현력|참여도|태도|능력)$|"
    r"핵심 아이디어|수행평가 출제 원칙|평가 출제 원칙|"
    r"필요성을 이해|방법을 습득|교육과정 성취기준|문맥 전환|평가 방법\s*:|"
    r"평가\s*결과(?:의)?\s*분석|정기시험|문항.*출제|학업성적관리|"
    r"교수.?학습.*평가.*계획|평가.*(?:목적|방침|원칙)|성취율|"
    r"학교교육과정의 범위|각 평가 기준의|학생 개개인|"
    r"수행평가는|과목의 평가는|신체장애 학생의 평가|성적처리|"
    r"기준고사 설정|평가에서의 인공지능|교차채점|영역별 평가 기준|"
    r"수행평가 방법 및 평가 기준|"
    r"학기 초 진단평가|성적\s*(?:산출|결과)|분할점수|기본점수|"
    r"수행평가.*(?:세부 계획|기준|배점)|강의식 수업|"
    r"자료 보관 및 관리|운영 시기|정서지원 프로그램|강의식수업|강의법|"
    r"작성하지 않은 경우|하지 않은 경우|도장의 개수가|"
    r"동점자 처리|^반영\s*비율|^평가\s*시기|"
    r"동점자처리|출제비율|학기말 반영|영역 만점|만점점수|"
    r"반영\s*비율|실시\s*여부|미응시|이의\s*신청|기타\s*사항|"
    r"세부\s*계획|동일\(유사\)한 영역|수행평가 과정과 결과|"
    r"동일\(유사\)한 .*영역|교육과정\s*(?:영역|성취)|"
    r"성취기준.*평가기준|기본방침|기본\s*점수|신체장애.*인정점|"
    r"수행평가.*척도|수행평가에.*학생|문항.*배점|"
    r"정의적 능력 평가|균형 있는 평가|학습과정평가|평가척도|"
    r"평가\s*(?:방법 및 내용|시 유의|영역|기준)$|"
    r"지필평가는|수행평가 출제계획|"
    r"미제출|미작성|무응답|총점\s*\(|"
    r"(?:작성|해결|제출|풀이|완성도|소감|필기).*(?:미만|이상|\d+\s*%|맞음)|"
    r"(?:한|못한|된|있는|없는|일|인)\s*경우$|"
    r"\d+\s*(?:자|개|가지|번|회|%)?\s*(?:이상|미만)|"
    r"제출함|작성하였으나|부분적으로|찾지 못|수행하였는가|양식에$|"
    r"전달력이 현저히|준비가 부실|형식을 지키지|보이지 않음|"
    r"내용 정리 부실|추가조치|영어|영문|English|Lesson"
)
SENTENCE_END_RE = re.compile(
    r"(?:한다|된다|있다|이다|돕는다|목적으로 한다|않음|부여|감점|미흡|틀림|옳음|맞음)[.!]?$|[.!?]$"
)
TASK_FRAGMENT_END_RE = re.compile(
    r"(?:하여|하며|하고|있으며|바탕으로|이용해|관점에서|적절하게|경우|과정과|위해)$"
)
TASK_TITLE_END_RE = re.compile(
    r"(?:탐구|프로젝트|보고서|포트폴리오|발표|토론|모델링|문제풀이|"
    r"활동|제작|시각화|논술|정리|노트|일지|신문|매거진|메거진|"
    r"작성하기|만들기|제작하기|분석하기|설명하기|해결하기|증명하기|"
    r"표현하기|바라보기|글쓰기)$"
)
TASK_METHOD_OPTION_RE = re.compile(
    r"서술.?논술|구술.?발표|토의.?토론|조사.?관찰|실기.?시연|"
    r"실험.?실습|포트폴리오|프로젝트|교사 관찰|자기평가|동료평가"
)
TASK_LABEL_RE = re.compile(
    r"^(?:수행평가명|평가명|수행평가영역|평가영역|평가 과제|수행 과제|"
    r"고사.?평가과제|과제명)\s*[:|]\s*"
)
COURSE_HEADING_MARKERS = (
    "교수학습및평가운영계획",
    "교수·학습및평가운영계획",
    "교수학습및평가계획서",
    "교수·학습및평가계획서",
    "교수학습-평가방법",
    "교수학습및평가방법",
    "평가세부계획",
)
EMPTY_CHECKBOXES = ("□", "◻", "☐", "▢", "▧")
TASK_COLUMN_LABEL_RE = re.compile(
    r"^(?:수행평가과제명|수행평가명|수행평가영역|평가과제명|고사평가과제|"
    r"과제명|평가명|평가영역|영역명)$"
)
TABLE_FIELD_LABEL_RE = re.compile(
    r"^(?:수행평가과제명|수행평가명|수행평가영역|평가과제명|고사평가과제|"
    r"과제명|평가명|평가영역|영역명|반영비율|평가비율|배점|만점|"
    r"평가방법|평가시기|평가요소|평가기준|채점기준|성취기준|성취수준|"
    r"관련단원|평가범위)$"
)
DIRECT_TASK_LABEL_RE = re.compile(
    r"^(?:수행평가과제명|수행평가명|평가과제명|고사평가과제|과제명|평가명)$"
)
STANDARD_CODE_RE = re.compile(r"\[((?:10|12)[가-힣A-Za-z][^\]\s]{2,23})\]")
METHOD_LABELS = (
    "서술·논술",
    "논·서술형",
    "조사·발표",
    "구술·발표",
    "토의·토론",
    "프로젝트",
    "실험·실습",
    "포트폴리오",
    "교사 관찰",
    "자기평가",
    "동료평가",
)
CATEGORY_PATTERNS = (
    ("reading", re.compile(r"독서|도서|책을|서평|북리뷰|독후")),
    ("modeling", re.compile(r"모델링|수학화|모형|시뮬레이션")),
    ("problem", re.compile(r"문제\s*(?:만들|제작|창작)|문항\s*(?:만들|제작|출제)|출제하기")),
    (
        "portfolio",
        re.compile(r"포트폴리오|수학\s*일지|러닝\s*저널|오답\s*(?:노트|문항)|성장\s*기록"),
    ),
    ("presentation", re.compile(r"발표|설명하기|수학\s*말하기|프레젠테이션|포스터")),
    ("inquiry", re.compile(r"탐구|연구|프로젝트|보고서")),
)
PROCESS_SIGNAL_RE = re.compile(
    r"초안|중간\s*보고서|피드백|수정|성찰|연구\s*질문|탐구\s*질문|"
    r"참고\s*문헌|출처|동료\s*평가|자기\s*평가|과정\s*기록|검증|한계"
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
OTHER_SUBJECT_RE = re.compile(
    r"국어|문학|화법|작문|언어와\s*매체|한국사|세계사|사회.?문화|윤리|"
    r"지리\s*탐구|영어|영미|한문|동사의\s*활용|생명과학|물리학|화학|"
    r"미술|음악|체육"
)
MATH_CONTEXT_RE = re.compile(
    r"수학|함수|방정식|부등식|수열|미분|적분|확률|통계|기하|도형|벡터|"
    r"행렬|지수|로그|삼각|다항식|실수|복소수|집합|명제|경우의\s*수|"
    r"이차곡선|좌표|연산|모델링|데이터|수치|그래프"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"malformed JSONL {path}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"JSONL object required {path}:{line_no}")
            yield value


def normalized_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalized_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    output: set[int] = set()
    for item in value:
        try:
            output.add(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(output)


def repair_title_spacing(value: str) -> str:
    """Repair common table/PDF joins without guessing every Korean word boundary."""
    text = unicodedata.normalize("NFKC", value)
    replacements = (
        (r"주제탐구", "주제 탐구"),
        (r"자유주제", "자유 주제"),
        (r"탐구보고서", "탐구 보고서"),
        (r"연구보고서", "연구 보고서"),
        (r"보고서\s*작성", "보고서 작성"),
        (r"문제해결", "문제 해결"),
        (r"문제분석", "문제 분석"),
        (r"문제만들기", "문제 만들기"),
        (r"문제탐구", "문제 탐구"),
        (r"문제풀이", "문제 풀이"),
        (r"해결전략", "해결 전략"),
        (r"수학적모델링", "수학적 모델링"),
        (r"모델링프로젝트", "모델링 프로젝트"),
        (r"최적해탐구", "최적해 탐구"),
        (r"포트\s*폴리오", "포트폴리오"),
        (r"(?<=[가-힣])포트폴리오", " 포트폴리오"),
        (r"도서기반", "도서 기반"),
        (r"독서기반", "독서 기반"),
        (r"수학독서", "수학 독서"),
        (r"독서활동", "독서 활동"),
        (r"탐구활동", "탐구 활동"),
        (r"제작활동", "제작 활동"),
        (r"탐구분석", "탐구 분석"),
        (r"탐구결과", "탐구 결과"),
        (r"탐구발표", "탐구 발표"),
        (r"활동발표", "활동 발표"),
        (r"수학탐구", "수학 탐구"),
        (r"기반수학", "기반 수학"),
        (r"활동수업", "활동 수업"),
        (r"수학과제탐구", "수학 과제 탐구"),
        (r"교과융합프로젝트", "교과 융합 프로젝트"),
        (r"단원정리노트만들기", "단원 정리 노트 만들기"),
        (r"방안논술", "방안 논술"),
        (r"수학자율", "수학 자율"),
        (r"토론문작성하기", "토론문 작성하기"),
        (r"학습지정리", "학습지 정리"),
        (r"배움일지", "배움 일지"),
        (r"하기및", "하기 및 "),
        (r"적\s+용한", "적용한"),
        (r"문\s+제", "문제"),
        (r"탐\s+구", "탐구"),
        (r"오답문항", "오답 문항"),
        (r"바\s+라보는", "바라보는"),
        (r"아름다\s+운", "아름다운"),
        (r"올바\s+른", "올바른"),
        (r"한자유", "한 자유"),
        (r"나만의\s*저축\s*상품\s*만들기", "나만의 저축 상품 만들기"),
        (r"환율을\s*이용한\s*여행\s*보고서", "환율을 이용한 여행 보고서"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return WHITESPACE_RE.sub(" ", text).strip()


def html_cell_text(value: str) -> str:
    text = HTML_BREAK_RE.sub(" ", value)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return repair_title_spacing(WHITESPACE_RE.sub(" ", text).strip(" |"))


def consume_rowspans(
    rowspans: dict[int, tuple[int, str]], cells: list[str], column: int
) -> int:
    while column in rowspans:
        remaining, text = rowspans[column]
        cells.append(text)
        if remaining <= 1:
            del rowspans[column]
        else:
            rowspans[column] = (remaining - 1, text)
        column += 1
    return column


def html_tables(value: object) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table_match in HTML_TABLE_RE.finditer(str(value or "")):
        rows: list[list[str]] = []
        rowspans: dict[int, tuple[int, str]] = {}
        for row_match in HTML_TABLE_ROW_RE.finditer(table_match.group(1)):
            cells: list[str] = []
            column = 0
            for cell_match in HTML_TABLE_CELL_RE.finditer(row_match.group(1)):
                column = consume_rowspans(rowspans, cells, column)
                attributes = cell_match.group(1)
                text = html_cell_text(cell_match.group(2))
                rowspan_match = re.search(r"\browspan\s*=\s*[\"']?(\d+)", attributes, re.I)
                colspan_match = re.search(r"\bcolspan\s*=\s*[\"']?(\d+)", attributes, re.I)
                rowspan = min(int(rowspan_match.group(1)), 50) if rowspan_match else 1
                colspan = min(int(colspan_match.group(1)), 50) if colspan_match else 1
                for offset in range(colspan):
                    cells.append(text)
                    if rowspan > 1:
                        rowspans[column + offset] = (rowspan - 1, text)
                column += colspan
            if rowspans:
                last_pending_column = max(rowspans)
                while column <= last_pending_column:
                    if column in rowspans:
                        column = consume_rowspans(rowspans, cells, column)
                    else:
                        cells.append("")
                        column += 1
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def compact_label(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value)


def table_task_candidates(value: object) -> dict[str, int]:
    candidates: dict[str, int] = {}
    for rows in html_tables(value):
        task_columns: list[int] = []
        for row in rows:
            header_cell_count = sum(
                bool(TABLE_FIELD_LABEL_RE.fullmatch(compact_label(cell))) for cell in row
            )
            for index, cell in enumerate(row):
                label = compact_label(cell)
                if DIRECT_TASK_LABEL_RE.fullmatch(label):
                    # Some plans put several 수행평가 names to the right of one
                    # explicit 과제명 header.  Keep those cells, while the strict
                    # reject rules below prevent methods, weights and field labels
                    # from leaking into the public title list.
                    for candidate in row[index + 1 :]:
                        name = normalize_task_name(candidate)
                        if not task_name_is_rejected(name):
                            candidates[name] = max(candidates.get(name, 0), 68)
                # A task-name cell in a vertical label/value table must not
                # turn the entire first column into title candidates.  Only
                # treat it as a column header when the row contains at least
                # one additional table-field header.
                if TASK_COLUMN_LABEL_RE.fullmatch(label) and header_cell_count >= 2:
                    task_columns.append(index)
        for column in sorted(set(task_columns)):
            for row in rows:
                if column >= len(row):
                    continue
                name = normalize_task_name(row[column])
                if task_name_is_rejected(name):
                    continue
                candidates[name] = max(candidates.get(name, 0), 58)
    return candidates


def heading_task_candidates(value: object) -> dict[str, int]:
    text = plain_text(value)
    candidates: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(
            r"^#{1,6}\s*(?:(?:[가-하]|\d+)\s*[.)]\s*)?(.+?)\s*$", line
        )
        if not match:
            continue
        name = normalize_task_name(re.sub(r"\s*\([^)]*(?:점|%)\)[^)]*$", "", match.group(1)))
        if (
            task_name_is_rejected(name)
            or not TASK_SIGNAL_RE.search(name)
            or len(name) > 45
            or not TASK_TITLE_END_RE.search(name)
        ):
            continue
        candidates[name] = 42
    return candidates


def normalize_task_name(raw: object) -> str:
    name = repair_title_spacing(str(raw)).strip(" |#*★☆:-▪∙•·○◦ㅇᄋ")
    name = re.sub(r"\bgfedcb?\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(
        r"^(?:<?t[dh]\s+)?(?:(?:row|col|l)?span|pan)"
        r"\s*=\s*[\"']?\d+[\"']?>?\s*",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(
        r"\s*[([][^)\]]*(?:\d+\s*(?:점|%)|감점|배점|반영)[^)\]]*[)\]]",
        "",
        name,
    )
    name = re.sub(r"^\*?\[(?:수행|평가)\]\s*", "", name)
    name = re.sub(r"^(?:[IVXⅠⅡⅢⅣⅤⅥ]+|[가-하]|\d+)\s*[.)]\s*", "", name)
    name = re.sub(
        r"^(?:수행평가과제명|수행평가명|수행평가영역|수행평가|평가과제명|"
        r"평가영역|과제명|평가명)\s*[:|·-]?\s*",
        "",
        name,
    )
    name = TASK_LABEL_RE.sub("", name).strip(" |#:-")
    name = re.sub(r"^(?:영역|과제)\s*\d+\s*[:.)-]\s*", "", name)
    name = re.sub(r"^(?:[가-하]|\d+)\s*[.)]\s*", "", name)
    name = re.sub(
        r"^(?:수행평가과제명|수행평가명|수행평가영역|수행평가|평가과제명|"
        r"평가영역|과제명|평가명)\s*[:|·-]?\s*",
        "",
        name,
    )
    name = re.sub(r"\s*[([]\s*\d+(?:\.\d+)?\s*(?:점|%)\s*[)\]]\s*$", "", name)
    name = re.sub(r"\s*[([]\s*\d+(?:\.\d+)?\s*점\s*만점\s*[)\]]\s*$", "", name)
    name = re.sub(
        r"\s*[([]\s*\d+(?:\.\d+)?\s*~\s*\d+(?:\.\d+)?\s*[)\]]\s*점\s*$",
        "",
        name,
    )
    name = re.sub(
        r"\s*[:;,]\s*\d+(?:\.\d+)?\s*(?:점|%)"
        r"(?:\s*[,/·]\s*\d+(?:\.\d+)?\s*(?:점|%))*\s*$",
        "",
        name,
    )
    name = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:점|%)\s*$", "", name)
    name = re.sub(r"\s*[([]\s*\d+(?:\.\d+)?\s*[)\]]\s*$", "", name)
    name = re.sub(r"\s+\d+\s*회\s*$", "", name)
    name = re.sub(r"\s*\(\s*평가기준\s*\d+단계\s*\)\s*$", "", name)
    return repair_title_spacing(name).strip(" |#:-▪∙•·")


def task_name_is_rejected(name: str) -> bool:
    method_options = TASK_METHOD_OPTION_RE.findall(name)
    return bool(
        not name
        or name in GENERIC_TASK_NAMES
        or len(name) < 3
        or len(name) > 60
        or name.startswith((")", "(", "]"))
        or bool(STANDARD_CODE_RE.search(name))
        or TASK_REJECT_RE.search(name)
        or SENTENCE_END_RE.search(name)
        or len(method_options) >= 2
        or any(marker in name for marker in (*EMPTY_CHECKBOXES, "☑", "■", "▸", "▶", "▪"))
        or name.count("·") >= 2
        or (len(name) > 48 and TASK_FRAGMENT_END_RE.search(name))
        or re.search(r"(?:적합성|완성도|충실도|준수 여부)$", name)
        or re.search(r"(?:함\.)?\s*\d+$", name)
        or re.fullmatch(r"\d+(?:\.\d+)?\s*(?:점|%)", name)
        or re.fullmatch(r"\d\s*(?:학년|학기)", name)
        or re.match(r"^(?:배점|만점|반영\s*비율|평가\s*횟수)(?:\s*\([^)]*\))?$", name)
        or (len(name) > 42 and not TASK_TITLE_END_RE.search(name))
        or (len(name) > 28 and name.endswith("경우"))
        or (len(name) > 18 and name.endswith("함"))
        or bool(re.search(r"평가\s*방법", name))
        or bool(re.search(r"(?:작성\s*내용|창의성|흥미도|이해도|연계성)$", name))
        or bool(re.search(r"(?:역량|능력\s*신장)$", name))
        or bool(MULTI_STEP_LIST_RE.search(name))
        or bool(OTHER_SUBJECT_RE.search(name) and not MATH_CONTEXT_RE.search(name))
        or bool(re.fullmatch(r"수학\s*과제\s*탐구", name))
        or bool(re.search(r"수학\s*과제\s*탐구의\s*(?:이해|실행과\s*평가)", name))
        or bool(re.fullmatch(r"교수\s*학습\s*활동", name))
        or "창의적 사고와 문화 활동" in name
        or "사이버 어울림활동" in name
        or bool(re.search(r"사회\s*현상의\s*이해와\s*탐구", name))
        or any(term in name for term in RUBRIC_TITLE_TERMS)
        or bool(SCORE_METADATA_RE.search(name))
        or bool(FIELD_OR_POLICY_RE.search(name))
        or bool(EXAM_OR_FIELD_RE.fullmatch(name))
        or bool(TEMPLATE_POLICY_RE.search(name))
        or bool(GENERIC_RUBRIC_CELL_RE.fullmatch(name))
        or bool(METHOD_OR_GENERIC_ACTIVITY_RE.fullmatch(name))
        or bool(METHOD_ONLY_COMBINATION_RE.fullmatch(name))
        or bool(re.search(r"(?:확인한\s*)?총\s*횟수$", name))
        or (len(name) > 32 and bool(re.search(r"(?:과|및|을|를|의)$", name)))
        or bool(re.search(r"^평가\s*내용\s*및\s*평가\s*기준", name))
        or name.count("수업") >= 2
        or bool(
            re.search(
                r"Character\s+Spotlight|영미소설|Supplementary\s+Reading|"
                r"Sculpt\s+Your\s+Dream|동사의\s*활용",
                name,
                re.IGNORECASE,
            )
        )
        or bool(re.search(r"gfedcb?|(?:<?t[dh]\s+)?(?:row|col)span\s*=", name, re.I))
        or ("경우" in name and "경우의 수" not in name)
        or (
            bool(re.search(r"(?:이상|미만)", name))
            and not bool(
                re.search(
                    r"(?:만들기|작성하기|탐구하기|보고서|프로젝트)$",
                    name,
                )
            )
        )
        or bool(re.fullmatch(r"[0-9\s~.,+×xX%점]+", name))
    )


def clean_task_names(value: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in normalized_strings(value):
        name = normalize_task_name(raw)
        if task_name_is_rejected(name) or name in seen:
            continue
        seen.add(name)
        result.append(name)
        if len(result) >= MAX_TASK_NAMES:
            break
    return result


def task_candidate_score(name: str, source_bonus: int = 0) -> tuple[int, int]:
    signals = len(TASK_SIGNAL_RE.findall(name))
    points_bonus = int(bool(re.search(r"\d+\s*(?:점|%)", name)))
    concise_bonus = int(len(name) <= 45)
    readability_bonus = min(name.count(" "), 4)
    title_bonus = 18 if TASK_TITLE_END_RE.search(name) else 0
    math_bonus = 5 if re.search(r"극한|미분|적분|함수|수열|확률|통계|기하|대수", name) else 0
    step_penalty = 8 if re.match(r"^(?:\[?\d+단계\]?|\d+\))", name) else 0
    score = (
        min(signals, 4) * 7
        + points_bonus * 3
        + concise_bonus
        + readability_bonus
        + title_bonus
        + math_bonus
        + source_bonus
        - step_penalty
    )
    return score, -len(name)


def subject_local_text(text: str, subject: str) -> tuple[str, bool]:
    """Trim multi-course documents to the subject section when a heading exists."""
    target = re.sub(r"\s+", "", unicodedata.normalize("NFKC", subject))
    lines = text.splitlines()
    start: int | None = None
    subject_mentions: list[int] = []
    for index, line in enumerate(lines):
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", line))
        if target in compact:
            subject_mentions.append(index)
            if start is None and any(marker in compact for marker in COURSE_HEADING_MARKERS):
                start = index
    if start is None:
        if not subject_mentions:
            return text, False
        start = 0
        end_search_start = subject_mentions[0] + 1
    else:
        end_search_start = start + 1
    end = len(lines)
    for index in range(end_search_start, len(lines)):
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", lines[index]))
        if (
            target not in compact
            and len(compact) <= 100
            and any(marker in compact for marker in COURSE_HEADING_MARKERS)
        ):
            end = index
            break
    return "\n".join(lines[start:end]).strip(), True


def derive_task_names(
    evidence: object, existing: object, subject: str
) -> tuple[list[str], str, dict[str, str]]:
    full_text = plain_text(evidence)
    text, localized = subject_local_text(full_text, subject)
    text_compact = re.sub(r"\s+", "", text)
    table_candidates = table_task_candidates(evidence)
    candidate_bonuses = dict(table_candidates)
    candidate_sources = {name: "table" for name in table_candidates}
    heading_candidates = heading_task_candidates(evidence)
    for name, bonus in heading_candidates.items():
        candidate_bonuses[name] = max(candidate_bonuses.get(name, 0), bonus)
        candidate_sources.setdefault(name, "heading")
    for name in clean_task_names(existing):
        if localized and re.sub(r"\s+", "", name) not in text_compact:
            continue
        if len(name) > 45 and not TASK_TITLE_END_RE.search(name):
            continue
        if (
            name not in table_candidates
            and name not in heading_candidates
            and not TASK_SIGNAL_RE.search(name)
        ):
            continue
        # Upstream candidates come from the bounded 수행평가 section and are
        # therefore safer than a later scan across every table in the source.
        candidate_bonuses[name] = max(candidate_bonuses.get(name, 0), 92)
        candidate_sources[name] = "section"
    for line in text.splitlines():
        cells = line.split("|") if "|" in line else [line]
        labelled_value_indices = {
            index + 1
            for index, cell in enumerate(cells[:-1])
            if TASK_COLUMN_LABEL_RE.fullmatch(compact_label(cell))
        }
        for index, cell in enumerate(cells):
            label_bonus = 36 if (
                index in labelled_value_indices
                or bool(TASK_LABEL_RE.search(cell.strip(" |#:-")))
            ) else 0
            name = normalize_task_name(cell)
            if task_name_is_rejected(name) or not TASK_SIGNAL_RE.search(name):
                continue
            if not label_bonus and (len(name) > 42 or not TASK_TITLE_END_RE.search(name)):
                continue
            candidate_bonuses[name] = max(candidate_bonuses.get(name, 0), label_bonus)
            candidate_sources.setdefault(name, "context")
    # Public task-name candidates must describe an observable task, product,
    # or action.  A table position alone is not enough because merged rubric
    # tables also contain unit names, policy labels and scoring dimensions.
    unique = [name for name in candidate_bonuses if TASK_SIGNAL_RE.search(name)]
    unique.sort(
        key=lambda name: task_candidate_score(name, candidate_bonuses[name]),
        reverse=True,
    )
    selected: list[str] = []
    seen_compact: set[str] = set()
    for name in unique:
        compact = compact_label(name)
        if not compact or compact in seen_compact:
            continue
        seen_compact.add(compact)
        selected.append(name)
        if len(selected) >= MAX_TASK_NAMES:
            break
    return selected, text, {name: candidate_sources.get(name, "context") for name in selected}


def task_title_basis(evidence: object, title: str, candidate_sources: dict[str, str]) -> str:
    if not title or title == "구체적 과제명 미탐지":
        return "missing"
    compact_title = compact_label(title)
    for table in html_tables(evidence):
        if compact_title and compact_title in compact_label(" ".join(sum(table, []))):
            return "table"
    for name in heading_task_candidates(evidence):
        if compact_label(name) == compact_title:
            return "heading"
    return candidate_sources.get(title, "context")


def selected_task_table(evidence: object, title: str) -> list[list[str]]:
    compact_title = compact_label(title)
    matches: list[tuple[int, list[list[str]]]] = []
    for table in html_tables(evidence):
        flat = " ".join(sum(table, []))
        if not compact_title or compact_title not in compact_label(flat):
            continue
        labels = compact_label(flat)
        score = sum(
            marker in labels
            for marker in ("평가개요", "성취기준", "평가요소", "채점기준", "평가방법")
        )
        matches.append((score, table))
    return max(matches, key=lambda item: (item[0], len(item[1])))[1] if matches else []


def row_values(rows: list[list[str]], labels: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for index, cell in enumerate(row):
            label = compact_label(cell)
            if any(value in label for value in labels):
                for value in row[index + 1 :]:
                    cleaned = repair_title_spacing(value).strip(" |,·")
                    if (
                        not cleaned
                        or compact_label(cleaned) == label
                        or cleaned in seen
                    ):
                        continue
                    seen.add(cleaned)
                    values.append(cleaned)
    return values


def unique_limited(values: Iterable[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = repair_title_spacing(value).strip(" |,·")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def assessment_structure(
    evidence: object, title: str, candidate_sources: dict[str, str] | None = None
) -> dict[str, object]:
    raw = str(evidence or "")
    plain = plain_text(raw)
    rows = selected_task_table(raw, title)
    table_text = " | ".join(sum(rows, [])) if rows else ""
    scope = table_text
    if not scope:
        position = plain.find(title) if title else -1
        scope = plain[max(0, position - 160) : position + 1800] if position >= 0 else plain[:1800]

    overview_values = row_values(rows, ("평가개요", "평가내용"))
    overview = " ".join(overview_values)
    if not overview:
        sentence_match = re.search(
            r"(?:평가개요|평가 내용)\s*\|?\s*(.{20,260}?)(?=\s*\||\n|$)", scope
        )
        overview = sentence_match.group(1) if sentence_match else ""
    overview_fragments = unique_limited(re.split(r"\s*\|\s*", overview), 6)
    overview = " ".join(
        value
        for value in overview_fragments
        if compact_label(value) not in {"평가개요", "평가내용", "세부평가내용"}
    )
    overview = repair_title_spacing(overview)
    if len(overview) > 220:
        overview = overview[:217].rstrip() + "…"

    checked_methods = re.findall(r"☑\s*([^☑□◻☐▢|\n]{2,24})", scope)
    methods: list[str] = []
    for label in METHOD_LABELS:
        if any(label in value for value in checked_methods):
            methods.append(label)
    if not methods:
        method_values = " ".join(row_values(rows, ("평가방법", "평가방식")))
        methods = [label for label in METHOD_LABELS if label in method_values]

    weight_values = row_values(rows, ("반영비율", "점수반영비율", "배점"))
    weight_candidates = re.findall(
        r"\d+(?:\.\d+)?\s*(?:점|%)", " ".join(weight_values) or scope
    )
    nonzero_weights = [
        value
        for value in weight_candidates
        if float(re.search(r"\d+(?:\.\d+)?", value).group()) > 0
    ]
    weights = unique_limited(nonzero_weights, 4)
    standards = unique_limited(STANDARD_CODE_RE.findall(scope), 4)

    criteria_text = " ".join(row_values(rows, ("평가요소", "채점기준")))
    criterion_candidates = re.findall(
        r"연구\s*동기(?:\s*및\s*목적)?|수학\s*개념|문제\s*해결(?:\s*능력)?|"
        r"탐구\s*(?:내용|과정|논리)|결과\s*(?:도출|분석)|참고\s*문헌|"
        r"정확성|논리성|창의성|의사소통|피드백\s*반영|성찰",
        criteria_text,
    )
    criteria = unique_limited(criterion_candidates, 4)
    basis = task_title_basis(raw, title, candidate_sources or {})
    return {
        "overview": overview,
        "methods": unique_limited(methods, 4),
        "weight": " · ".join(weights),
        "standards": standards,
        "criteria": criteria,
        "basis": basis,
    }


def assessment_category(title: str, structure: dict[str, object], evidence: object) -> str:
    # Curated rankings must describe the displayed task itself.  A plan often
    # places several task columns in one table, so an overview/criteria row can
    # contain words belonging to a different task (for example a reading task
    # beside a written problem-solving task).  Categorising from that combined
    # row makes a clean title appear in the wrong curated list.  Use the exact
    # published task name as the category evidence.
    for category, pattern in CATEGORY_PATTERNS:
        if pattern.search(title):
            return category
    return ""


def priority_evidence(
    title: str,
    structure: dict[str, object],
    marker_counts: dict[str, object],
    evidence: object,
    category: str,
) -> tuple[int, list[str]]:
    score = 0
    signals: list[str] = []
    basis = str(structure.get("basis") or "")
    if basis in {"table", "heading"}:
        score += 14
        signals.append("과제명 원문 구조 확인")
    if int(marker_counts.get("achievement_standard") or 0) > 0 and structure.get("standards"):
        score += 12
        signals.append("성취기준 연결")
    if int(marker_counts.get("rubric") or 0) > 0:
        score += 12
        signals.append("채점기준 확인")
    if int(marker_counts.get("assessment_method") or 0) > 0 and structure.get("methods"):
        score += 9
        signals.append("평가방법 명시")
    if int(marker_counts.get("weight_or_points") or 0) > 0 and structure.get("weight"):
        score += 7
        signals.append("배점·반영비율 명시")
    if structure.get("overview"):
        score += 7
        signals.append("평가개요 확인")
    process_hits = len(set(PROCESS_SIGNAL_RE.findall(plain_text(evidence))))
    if process_hits >= 2:
        score += min(12, 4 + process_hits)
        signals.append("과정·피드백 증거")
    if category and len(title) >= 10 and title not in GENERIC_TASK_NAMES:
        score += 8
        signals.append("구체적 과제 구조")
    if title == "구체적 과제명 미탐지" or title in GENERIC_TASK_NAMES:
        score -= 30
    return max(0, score), signals


def structured_excerpt(
    title: str,
    structure: dict[str, object],
    source_labels: list[str] | None = None,
) -> str:
    parts = [f"과제명: {title}"]
    if title == "구체적 과제명 미탐지" and source_labels:
        parts.append("원문 평가영역·표현: " + " · ".join(source_labels[:3]))
    if structure.get("overview"):
        parts.append(f"평가 개요: {structure['overview']}")
    if structure.get("methods"):
        parts.append("평가 방법: " + " · ".join(structure["methods"]))
    if structure.get("weight"):
        parts.append(f"배점·반영: {structure['weight']}")
    if structure.get("standards"):
        parts.append("성취기준: " + ", ".join(structure["standards"]))
    if structure.get("criteria"):
        parts.append("평가 요소: " + " · ".join(structure["criteria"]))
    return "\n".join(parts)[:MAX_EXCERPT_CHARS]


def plain_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(value or "")))
    text = HTML_ROW_RE.sub("\n", text)
    text = HTML_CELL_RE.sub(" | ", text)
    text = HTML_BREAK_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = MULTICELL_RE.sub(" | ", text)
    text = MARKDOWN_RULE_RE.sub("\n", text)
    lines: list[str] = []
    for line in text.splitlines():
        line = WHITESPACE_RE.sub(" ", line).strip(" |")
        if line:
            lines.append(line)
    return MULTILINE_RE.sub("\n\n", "\n".join(lines)).strip()


def evidence_excerpt(text: str, task_names: list[str]) -> str:
    if not text:
        return ""
    position = -1
    for marker in (*task_names, *EXCERPT_MARKERS):
        position = text.find(marker)
        if position >= 0:
            break
    start = max(0, position - 100) if position >= 0 else 0
    excerpt = text[start : start + MAX_EXCERPT_CHARS]
    if start > 0:
        excerpt = "…" + excerpt.lstrip()
    if start + MAX_EXCERPT_CHARS < len(text):
        excerpt = excerpt.rstrip() + "…"
    return excerpt


def resolve_region(source: dict[str, object]) -> str:
    explicit = str(source.get("region") or "").strip()
    if explicit:
        return explicit
    saved_path = str(source.get("saved_path") or "").replace("\\", "/")
    match = re.search(r"(?:^|/)4ga/([^/]+)/", saved_path)
    return match.group(1) if match else ""


def load_school_districts(path: Path) -> dict[str, tuple[str, str]]:
    output: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            school_code = str(row.get("school_code") or "").strip()
            region = str(row.get("region") or row.get("region_sido") or "").strip()
            district = str(row.get("district") or row.get("region_sgg") or "").strip()
            if not school_code or not region or not district:
                continue
            value = (region, district)
            if school_code in output and output[school_code] != value:
                raise SystemExit(f"conflicting school roster values for {school_code}")
            output[school_code] = value
    if not output:
        raise SystemExit("school roster contains no usable district values")
    return output


def case_identifier(source_sha256: str, curriculum: str, subject: str) -> str:
    canonical = f"{source_sha256}|{curriculum}|{subject}".encode()
    return hashlib.sha256(canonical).hexdigest()[:24]


def case_values(
    row: dict[str, object], school_districts: dict[str, tuple[str, str]]
) -> tuple[object, ...]:
    source = row.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    curriculum = str(row.get("resolved_curriculum") or "shared")
    subject = str(row.get("subject") or "").strip()
    source_sha256 = str(row.get("sha256") or "").strip()
    if not source_sha256 or not subject:
        raise SystemExit("catalog row missing source sha256 or subject")
    task_names, normalized_evidence, candidate_sources = derive_task_names(
        row.get("evidence_text"), row.get("task_name_candidates"), subject
    )
    action_tags = sorted(set(normalized_strings(row.get("action_tags"))))
    task_like_names = [name for name in task_names if TASK_SIGNAL_RE.search(name)]
    primary_task_name = (
        task_like_names[0] if task_like_names else "구체적 과제명 미탐지"
    )
    if task_like_names:
        task_names = [primary_task_name] + [
            name for name in task_names if name != primary_task_name
        ]
    marker_counts = row.get("marker_counts") or {}
    if not isinstance(marker_counts, dict):
        marker_counts = {}
    structure_title = (
        primary_task_name
        if primary_task_name != "구체적 과제명 미탐지"
        else (task_names[0] if task_names else primary_task_name)
    )
    structure = assessment_structure(
        row.get("evidence_text"), structure_title, candidate_sources
    )
    if primary_task_name == "구체적 과제명 미탐지":
        structure["basis"] = "area" if task_names else "missing"
    category = (
        assessment_category(primary_task_name, structure, row.get("evidence_text"))
        if primary_task_name != "구체적 과제명 미탐지"
        else ""
    )
    priority_score, priority_signals = priority_evidence(
        primary_task_name,
        structure,
        marker_counts,
        row.get("evidence_text"),
        category,
    )
    excerpt = structured_excerpt(primary_task_name, structure, task_names)
    years = normalized_ints(row.get("academic_years"))
    grades = normalized_ints(row.get("grades"))
    semesters = normalized_ints(row.get("semesters"))
    source_url = str(source.get("source_url") or "").strip()
    if source_url and "schoolinfo.go.kr" not in source_url:
        source_url = ""
    school_code = str(source.get("school_code") or "").strip()
    region = resolve_region(source)
    roster_value = school_districts.get(school_code)
    if roster_value is None or roster_value[0] != region:
        raise SystemExit(
            "source-backed district lookup failed for "
            f"school_code={school_code!r}, region={region!r}"
        )
    district = roster_value[1]
    case_id = case_identifier(source_sha256, curriculum, subject)
    return (
        case_id,
        source_sha256,
        curriculum,
        str(row.get("curriculum_resolution_basis") or ""),
        subject,
        school_code,
        str(source.get("school_name") or ""),
        region,
        district,
        json.dumps(years, ensure_ascii=False, separators=(",", ":")),
        json.dumps(grades, ensure_ascii=False, separators=(",", ":")),
        json.dumps(semesters, ensure_ascii=False, separators=(",", ":")),
        str(source.get("candidate_name") or ""),
        source_url,
        str(row.get("extract_status") or "unknown"),
        primary_task_name,
        json.dumps(task_names, ensure_ascii=False, separators=(",", ":")),
        json.dumps(action_tags, ensure_ascii=False, separators=(",", ":")),
        int(marker_counts.get("rubric") or 0),
        int(marker_counts.get("achievement_standard") or 0),
        int(marker_counts.get("weight_or_points") or 0),
        int(marker_counts.get("assessment_method") or 0),
        int(row.get("evidence_score") or 0),
        int(row.get("review_score") or 0),
        excerpt,
        len(excerpt),
        int(row.get("char_count") or 0),
        str(structure.get("overview") or ""),
        json.dumps(structure.get("methods") or [], ensure_ascii=False, separators=(",", ":")),
        str(structure.get("weight") or ""),
        json.dumps(structure.get("standards") or [], ensure_ascii=False, separators=(",", ":")),
        json.dumps(structure.get("criteria") or [], ensure_ascii=False, separators=(",", ":")),
        str(structure.get("basis") or "context"),
        category,
        priority_score,
        json.dumps(priority_signals, ensure_ascii=False, separators=(",", ":")),
    )


SCHEMA_SQL = """
PRAGMA application_id = 1296127059;
PRAGMA user_version = 1;
PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE subject_stats (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    documents INTEGER NOT NULL CHECK (documents >= 0),
    schools INTEGER NOT NULL CHECK (schools >= 0),
    academic_years_json TEXT NOT NULL,
    grade1_documents INTEGER NOT NULL,
    grade2_documents INTEGER NOT NULL,
    grade3_documents INTEGER NOT NULL,
    rubric_documents INTEGER NOT NULL,
    achievement_standard_documents INTEGER NOT NULL,
    weight_or_points_documents INTEGER NOT NULL,
    assessment_method_documents INTEGER NOT NULL,
    median_review_score REAL,
    task_name_candidates INTEGER NOT NULL,
    small_sample INTEGER NOT NULL CHECK (small_sample IN (0, 1)),
    coverage_found INTEGER,
    coverage_ambiguous INTEGER,
    coverage_not_found INTEGER,
    coverage_offering_unknown INTEGER,
    coverage_extraction_failed INTEGER,
    PRIMARY KEY (curriculum, subject)
) WITHOUT ROWID;

CREATE TABLE subject_action_tags (
    curriculum TEXT NOT NULL,
    subject TEXT NOT NULL,
    tag TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    school_count INTEGER NOT NULL,
    PRIMARY KEY (curriculum, subject, tag),
    FOREIGN KEY (curriculum, subject)
        REFERENCES subject_stats(curriculum, subject)
) WITHOUT ROWID;

CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    curriculum TEXT NOT NULL,
    curriculum_basis TEXT NOT NULL,
    subject TEXT NOT NULL,
    school_code TEXT NOT NULL,
    school_name TEXT NOT NULL,
    region TEXT NOT NULL,
    district TEXT NOT NULL,
    academic_years_json TEXT NOT NULL,
    grades_json TEXT NOT NULL,
    semesters_json TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    extract_status TEXT NOT NULL,
    primary_task_name TEXT NOT NULL,
    task_names_json TEXT NOT NULL,
    action_tags_json TEXT NOT NULL,
    rubric_marker_count INTEGER NOT NULL,
    achievement_standard_marker_count INTEGER NOT NULL,
    weight_or_points_marker_count INTEGER NOT NULL,
    assessment_method_marker_count INTEGER NOT NULL,
    evidence_score INTEGER NOT NULL,
    review_score INTEGER NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    excerpt_char_count INTEGER NOT NULL CHECK (excerpt_char_count <= 902),
    source_char_count INTEGER NOT NULL,
    summary_overview TEXT NOT NULL,
    methods_json TEXT NOT NULL,
    weight_summary TEXT NOT NULL,
    standards_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    title_basis TEXT NOT NULL,
    category TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    priority_signals_json TEXT NOT NULL
);

CREATE TABLE case_action_tags (
    case_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (case_id, tag),
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
) WITHOUT ROWID;

CREATE TABLE case_task_names (
    case_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    PRIMARY KEY (case_id, position),
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
) WITHOUT ROWID;

CREATE INDEX idx_cases_curriculum_subject_review
ON cases(curriculum, subject, review_score DESC, case_id);

CREATE INDEX idx_cases_subject_review
ON cases(subject, review_score DESC, case_id);

CREATE INDEX idx_cases_region_district_subject
ON cases(region, district, subject, review_score DESC);

CREATE INDEX idx_cases_category_priority
ON cases(category, priority_score DESC, case_id);

CREATE INDEX idx_case_action_tags_tag_case
ON case_action_tags(tag, case_id);

CREATE VIRTUAL TABLE cases_fts USING fts5(
    primary_task_name,
    evidence_excerpt,
    school_name,
    subject,
    content='cases',
    content_rowid='rowid',
    tokenize='unicode61'
);
"""


CASE_INSERT_SQL = """
INSERT INTO cases (
    case_id, source_sha256, curriculum, curriculum_basis, subject,
    school_code, school_name, region, district, academic_years_json, grades_json,
    semesters_json, candidate_name, source_url, extract_status,
    primary_task_name, task_names_json, action_tags_json,
    rubric_marker_count, achievement_standard_marker_count,
    weight_or_points_marker_count, assessment_method_marker_count,
    evidence_score, review_score, evidence_excerpt, excerpt_char_count,
    source_char_count, summary_overview, methods_json, weight_summary,
    standards_json, criteria_json, title_basis, category, priority_score,
    priority_signals_json
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
)
"""


def insert_subjects(
    connection: sqlite3.Connection,
    trends: dict[str, object],
    coverage: dict[str, object],
) -> int:
    groups = trends.get("subject_groups") or {}
    by_subject = coverage.get("by_subject") or {}
    if not isinstance(groups, dict) or not isinstance(by_subject, dict):
        raise SystemExit("invalid trends or coverage summary")
    for key in sorted(groups):
        row = groups[key]
        if not isinstance(row, dict):
            continue
        curriculum = str(row.get("curriculum") or "shared")
        subject = str(row.get("subject") or "")
        coverage_row = by_subject.get(f"{curriculum}:{subject}")
        if not isinstance(coverage_row, dict):
            coverage_row = {}
        connection.execute(
            """
            INSERT INTO subject_stats VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                curriculum,
                subject,
                int(row.get("documents") or 0),
                int(row.get("schools") or 0),
                json.dumps(row.get("academic_years") or [], separators=(",", ":")),
                int(row.get("grade1_documents") or 0),
                int(row.get("grade2_documents") or 0),
                int(row.get("grade3_documents") or 0),
                int(row.get("rubric_documents") or 0),
                int(row.get("achievement_standard_documents") or 0),
                int(row.get("weight_or_points_documents") or 0),
                int(row.get("assessment_method_documents") or 0),
                row.get("median_review_score") or None,
                int(row.get("task_name_candidates") or 0),
                int(int(row.get("documents") or 0) < 25),
                coverage_row.get("found"),
                coverage_row.get("found_curriculum_ambiguous"),
                coverage_row.get("not_found_in_collected_plans"),
                coverage_row.get("offering_unknown"),
                coverage_row.get("extraction_failed"),
            ),
        )
        document_tags = row.get("action_tag_document_counts") or {}
        school_tags = row.get("action_tag_school_counts") or {}
        if not isinstance(document_tags, dict) or not isinstance(school_tags, dict):
            continue
        for tag in sorted(document_tags):
            connection.execute(
                "INSERT INTO subject_action_tags VALUES (?, ?, ?, ?, ?)",
                (
                    curriculum,
                    subject,
                    tag,
                    int(document_tags.get(tag) or 0),
                    int(school_tags.get(tag) or 0),
                ),
            )
    return len(groups)


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def file_record(path: Path, root: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": relative_to_root(path, root),
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    derived = root / "data" / "derived"
    publish = root / "data" / "publish"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        type=Path,
        default=derived / "math_assessment_school_subject_catalog_v2.jsonl",
    )
    parser.add_argument(
        "--trends",
        type=Path,
        default=derived / "math_assessment_subject_trends_v2.json",
    )
    parser.add_argument(
        "--coverage-summary",
        type=Path,
        default=derived / "math_assessment_school_subject_coverage_v2_summary.json",
    )
    parser.add_argument(
        "--validation",
        type=Path,
        default=derived / "math_assessment_catalog_validation_v2.json",
    )
    parser.add_argument(
        "--completion",
        type=Path,
        default=derived / "math_assessment_final_pipeline_completion.json",
    )
    parser.add_argument(
        "--schools",
        type=Path,
        default=derived / "schoolinfo_schools.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=publish / "math_assessment_catalog.sqlite",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=publish / "math_assessment_publish_manifest.json",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    inputs = [
        args.catalog,
        args.trends,
        args.coverage_summary,
        args.validation,
        args.completion,
        args.schools,
    ]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise SystemExit("missing inputs: " + ", ".join(missing))
    if (args.output.exists() or args.manifest_output.exists()) and not args.replace:
        raise SystemExit("output exists; rerun with --replace to atomically rebuild")

    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    if validation.get("passed") is not True:
        raise SystemExit("source catalog validation has not passed")
    expected_rows = int(validation.get("counts", {}).get("strict_rows") or 0)
    trends = json.loads(args.trends.read_text(encoding="utf-8"))
    coverage = json.loads(args.coverage_summary.read_text(encoding="utf-8"))
    school_districts = load_school_districts(args.schools)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=args.output.stem + "_", suffix=".partial", dir=args.output.parent
    )
    os.close(file_descriptor)
    temp_path = Path(temp_name)
    case_count = 0
    try:
        connection = sqlite3.connect(temp_path)
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.executescript(SCHEMA_SQL)
        subject_count = insert_subjects(connection, trends, coverage)
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "source_catalog_rows": expected_rows,
            "source_validation_passed": True,
            "unit_of_analysis": "one source document x detected math subject",
            "interpretation_warning": (
                "평가계획에서 미검출은 해당 학교의 과목 미개설을 의미하지 않음"
            ),
            "full_source_text_published": False,
            "district_source": "SCHOOLINFO school roster exact school_code and region",
        }
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                for key, value in sorted(metadata.items())
            ],
        )
        for row in read_jsonl(args.catalog):
            values = case_values(row, school_districts)
            connection.execute(CASE_INSERT_SQL, values)
            case_id = str(values[0])
            for tag in json.loads(str(values[17])):
                connection.execute("INSERT INTO case_action_tags VALUES (?, ?)", (case_id, tag))
            for position, task_name in enumerate(json.loads(str(values[16]))):
                connection.execute(
                    "INSERT INTO case_task_names VALUES (?, ?, ?)",
                    (case_id, position, task_name),
                )
            case_count += 1
        if case_count != expected_rows:
            raise SystemExit(f"case count mismatch: expected={expected_rows}, actual={case_count}")
        connection.execute(
            """
            INSERT INTO cases_fts(
                rowid, primary_task_name, evidence_excerpt, school_name, subject
            )
            SELECT rowid, primary_task_name, evidence_excerpt, school_name, subject
            FROM cases
            """
        )
        connection.commit()
        connection.execute("PRAGMA optimize")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"SQLite integrity check failed: {integrity}")
        connection.execute("VACUUM")
        connection.close()
        os.replace(temp_path, args.output)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "builder": relative_to_root(Path(__file__), root),
        "inputs": [file_record(path, root) for path in inputs],
        "output": file_record(args.output, root),
        "counts": {
            "subjects": subject_count,
            "cases": case_count,
            "expected_cases": expected_rows,
        },
        "privacy": {
            "full_source_text_published": False,
            "local_source_paths_published": False,
            "maximum_excerpt_chars": MAX_EXCERPT_CHARS + 2,
        },
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_temp = args.manifest_output.with_suffix(args.manifest_output.suffix + ".partial")
    manifest_temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(manifest_temp, args.manifest_output)
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
