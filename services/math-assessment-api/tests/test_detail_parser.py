import json
import sqlite3

import pytest
from scripts.audit_math_assessment_table_structure import audit_html
from scripts.build_math_assessment_detail_db import SCHEMA_SQL, build_details, detail_priority
from scripts.build_math_assessment_publish_db import case_identifier
from scripts.math_assessment_detail_parser import (
    _hinted_table_items,
    _matched_rubric_html,
    _table_fragments_with_spans,
    balance_table_tags,
    explicit_segment_title,
    heading_title_is_structural,
    labelled_numeric_fields,
    markdown_fragment_to_html,
    parse_assessment_section,
    segment_subject_alignment,
    source_is_teaching_schedule_only,
    teaching_schedule_header_evidence,
)
from scripts.repair_math_assessment_titles import (
    credible_title,
    deduplicate_titles,
    source_aligned_catalog_spelling,
    source_is_non_math_leak,
    strict_source_titles,
)


def test_nested_table_fragment_retains_outer_tail_and_exact_source_span():
    table = (
        "<table><tr><td>채점기준<table><tr><td>10점</td></tr></table></td></tr>"
        "<tr><td>마지막 20점</td></tr></table>"
    )
    source = "앞부분\n" + table + "\n뒷부분"
    fragments = _table_fragments_with_spans(source)
    assert len(fragments) == 1
    start, end, recovered = fragments[0]
    assert recovered == source[start:end] == table


def test_overview_point_total_wins_over_internal_one_point_journal_scale():
    source = (
        "<table><tr><td>평가 시기</td><td>1학기 수시 (3~7월)</td>"
        "<td>점수</td><td>20</td></tr><tr><td>평가요소</td><td>배점</td></tr>"
        "<tr><td>성찰일지</td><td>하나의 성찰일지를 1점 만점으로 산출한다.</td></tr></table>"
    )
    assert labelled_numeric_fields(source) == {"score": "20점"}


def test_numeric_overview_does_not_promote_rubric_points_or_choose_between_totals():
    rubric = (
        "<table><tr><th>평가요소</th><th>점수</th></tr><tr><td>풀이</td><td>5</td></tr></table>"
    )
    assert labelled_numeric_fields(rubric) == {}
    source = (
        "<table><tr><td>영역 만점</td><td>100점</td><td>반영 비율</td><td>20%</td></tr>"
        "<tr><td>만점</td><td>20점</td></tr></table>"
    )
    assert labelled_numeric_fields(source) == {"weight": "20%"}


def test_numeric_overview_ignores_exam_and_whole_performance_summary_totals():
    source = (
        "<table><tr><th>평가유형</th><th>정기시험</th><th>수행평가</th><th>합계</th></tr>"
        "<tr><td>반영비율</td><td>60%</td><td>40%</td><td>100%</td></tr></table>"
    )
    assert labelled_numeric_fields(source) == {}
    all_performance = source.replace("<th>정기시험</th>", "").replace("<td>60%</td>", "")
    assert labelled_numeric_fields(all_performance) == {}
    transposed = (
        "<table><tr><td>평가종류</td><td>수행평가</td></tr>"
        "<tr><td>반영비율</td><td>100%</td></tr>"
        "<tr><td>영역별 만점(반영비율)</td><td>25점(25%)</td></tr></table>"
    )
    assert labelled_numeric_fields(transposed)["weight"] == "25%"


def test_task_policy_headings_are_not_published_as_assessment_names():
    assert heading_title_is_structural(
        "AI 리서치를 통한 대수학적 원리 탐색 및 가치 비평활동 수행평가의 유의사항"
    )
    assert heading_title_is_structural("유의사항 안내: 전자기기를 차단하고 대면 관찰하여 평가")
    assert not heading_title_is_structural("AI 리서치를 통한 대수학적 원리 탐색 및 가치 비평활동")


def test_lost_pdf_rows_still_identify_a_teaching_calendar_header():
    source = (
        "<p>1. 함수</p><p>12월</p><p>주</p><p>단원명 (영역명)</p>"
        "<p>교육과정 성취기준</p><p>수업방법</p><p>평가방법</p>"
        "<p>수업・평가 연계의 주안점</p><p>다음 시기 2학기</p>"
        "<p>★수행평가 연계: 함수 개념을 말과 글로 설명하기</p>"
    )
    assert teaching_schedule_header_evidence(source)
    assert source_is_teaching_schedule_only(source)


def test_schedule_guard_preserves_real_scoring_and_distant_policy_words():
    header = "시기 월주 단원명 교육과정 성취기준 수업방법 평가방법 수업-평가 연계 주안점"
    real = header + "<table><tr><th>채점기준</th><th>배점</th></tr>" \
        "<tr><td>과정 설명</td><td>20점</td></tr></table>"
    assert not source_is_teaching_schedule_only(real)
    assert not teaching_schedule_header_evidence(
        "수업방법을 개선한다. " + "수학 탐구 활동을 되돌아본다. " * 30
        + "교육과정 성취기준, 시기, 단원명, 평가방법을 참고한다."
    )


def test_audit_separates_teaching_calendar_from_assessment_scoring() -> None:
    schedule = """<table><tbody><tr><th colspan="6">교수학습 계획</th></tr>
      <tr><th>월 (행사)</th><th>주</th><th>단원명 (수업주제)</th>
      <th>교육과정 성취기준</th><th>평가요소</th><th>평가방법</th></tr>
      <tr><td>8</td><td>4주</td><td>함수의 극한</td><td>성취기준</td>
      <td>극한의 뜻 설명</td><td>수행평가 연계</td></tr></tbody></table>"""
    rubric = """<table><tr><th>평가영역</th><th>평가시기</th><th>성취기준</th>
      <th>채점기준</th><th>배점</th></tr>
      <tr><td>함수 탐구</td><td>9월 3주</td><td>함수</td><td>설명</td><td>20점</td></tr></table>"""
    assert "instruction_schedule_in_source" in audit_html(schedule)["flags"]
    assert "instruction_schedule_in_rubric" in audit_html(schedule, is_rubric=True)["flags"]
    assert "instruction_schedule_in_rubric" not in audit_html(rubric, is_rubric=True)["flags"]


def test_non_math_source_leak_is_detected_without_math_evidence() -> None:
    social_source = (
        "평가영역명 주제 토의 수행과제 타인의 고통에 공감하고 "
        "사회적 연대를 법으로 강제할 수 있는지 토의한다."
    )
    math_source = social_source + " 수학적 모델과 함수를 사용한다."

    assert source_is_non_math_leak("공통수학1", social_source)
    assert not source_is_non_math_leak("공통수학1", math_source)


def test_catalog_spelling_only_repairs_source_equivalent_spacing() -> None:
    assert (
        source_aligned_catalog_spelling(
            "경우의 수를 적용한 실생 활 문제 탐구 및 발표",
            ["경우의 수를 적용한 실생활 문제 탐구 및 발표"],
        )
        == "경우의 수를 적용한 실생활 문제 탐구 및 발표"
    )
    assert (
        source_aligned_catalog_spelling(
            "수학 주제 탐구",
            ["수학 독서 탐구"],
        )
        == "수학 주제 탐구"
    )


def test_subject_code_alignment_does_not_confuse_math_one_and_two() -> None:
    math_two = "<table><tr><td>[12수학Ⅱ01-04] 연속함수의 성질</td></tr></table>"
    math_one = "<table><tr><td>[12수학Ⅰ01-01] 지수함수와 로그함수</td></tr></table>"

    assert segment_subject_alignment(math_two, "수학Ⅰ") == "other"
    assert segment_subject_alignment(math_two, "수학Ⅱ") == "expected"
    assert segment_subject_alignment(math_one, "수학Ⅰ") == "expected"
    assert segment_subject_alignment(math_one, "수학Ⅱ") == "other"


def test_subject_code_alignment_accepts_grade_course_separator_variant() -> None:
    source = "<table><tr><td>[12-대수01-05] 상용로그를 이해한다.</td></tr></table>"

    assert segment_subject_alignment(source, "대수") == "expected"
    assert segment_subject_alignment(source, "기하") == "other"


def test_pdf_latin_roman_numerals_keep_calculus_courses_distinct() -> None:
    assert segment_subject_alignment("[12미적I-01-01] 극한", "미적분Ⅰ") == "expected"
    assert segment_subject_alignment("[12미적II-01-01] 극한", "미적분Ⅱ") == "expected"
    assert segment_subject_alignment("[12미적II-01-01] 극한", "미적분Ⅰ") == "other"


def test_rubric_matching_requires_a_criteria_header_and_exact_task_cell() -> None:
    source = """
<table>
<tr><td>3월</td><td>오리엔테이션, 평가 기준 및 수업 규칙</td></tr>
<tr><td>4월</td><td>수행평가 독서를 통한 수학의 이해 주제 선정</td></tr>
</table>
<table>
<tr><th>평가 항목</th><th>평가 관점 및 배점 기준</th><th>배점</th></tr>
<tr><td>독서를 통한 수학의 이해 (20점)</td><td>탐구 주제가 분명함</td><td>20</td></tr>
<tr><td>다른 과제</td><td>독서를 통한 수학의 이해 활동 참조</td><td>5</td></tr>
</table>
"""
    rubric = _matched_rubric_html(source, "독서를 통한 수학의 이해")
    assert "탐구 주제가 분명함" in rubric
    assert "오리엔테이션" not in rubric
    assert "다른 과제" not in rubric


def test_assessment_type_matrix_uses_the_tasks_own_weight_and_schedule() -> None:
    source = """
# 미적분Ⅰ
## 수행평가 계획
<table>
<tr><th>평가 유형</th><th>정기시험</th><th colspan="2">수행평가</th></tr>
<tr><th>반영비율</th><td>50%</td><td colspan="2">50%</td></tr>
<tr><th>횟수/영역</th><td>1회</td><td>수학 독서 보고서</td><td>미분 활용 탐구</td></tr>
<tr><th>평가 방법</th><td>선택형</td><td>프로젝트</td><td>프로젝트</td></tr>
<tr><th>영역만점(반영비율)</th><td>80점 (50%)</td><td>100점 (30%)</td><td>100점 (20%)</td></tr>
<tr><th>평가 시기</th><td>4월</td><td>3월</td><td>6월</td></tr>
<tr><th>성취기준</th><td>[12미적I-01-01]</td><td>[12미적I-01-01]</td><td>[12미적I-02-01]</td></tr>
</table>
"""
    section = parse_assessment_section(source, "미적분Ⅰ", ("수학 독서 보고서", "미분 활용 탐구"))
    assert [
        (item.title, item.method, item.score, item.weight, item.timing) for item in section.items
    ] == [
        ("수학 독서 보고서", "프로젝트", "100점", "30%", "3월"),
        ("미분 활용 탐구", "프로젝트", "100점", "20%", "6월"),
    ]


def test_a_task_mention_in_a_teaching_schedule_cannot_supply_a_card() -> None:
    schedule = """
<table>
<tr><th>단원명</th><th>성취기준</th><th>수업 방법</th><th>평가방법</th><th>진도 계획</th></tr>
<tr><td>함수</td><td>[12대수01-01]</td><td>토론</td><td>자료 분석 프로젝트</td><td>5월</td></tr>
</table>
"""
    assert (
        _hinted_table_items(schedule, "대수", "subject_heading", 0, ("자료 분석 프로젝트",)) == []
    )


def test_assessment_method_matrix_reads_only_the_performance_columns() -> None:
    source = """
# 미적분Ⅰ
## 평가 영역 및 반영 비율
<table>
<tr><th>평가방법</th><th colspan="2">정기시험</th><th colspan="2">수행평가</th></tr>
<tr><th>반영비율</th><td colspan="2">60%</td><td colspan="2">40%</td></tr>
<tr><th rowspan="2">평가 요소<br>(방법)</th><td colspan="2">1회고사</td>
    <td rowspan="2">함수 변화율 설명</td><td rowspan="2">미분 주제 탐구 보고서</td></tr>
<tr><td>선택형</td><td>서술형</td></tr>
<tr><th>영역 만점</th><td>80점</td><td>20점</td><td>100점</td><td>100점</td></tr>
<tr><th>세부 반영 비율(%)</th><td>48%</td><td>12%</td><td>15%</td><td>25%</td></tr>
<tr><th>평가 시기</th><td colspan="2">고사기간</td><td>9월</td><td>8~11월</td></tr>
<tr><th>성취기준</th><td colspan="2">[12미적Ⅰ-01-01]</td>
    <td>[12미적Ⅰ-01-01]</td><td>[12미적Ⅰ-02-01]</td></tr>
</table>
"""
    items = parse_assessment_section(source, "미적분Ⅰ").items
    assert [(item.title, item.score, item.weight, item.timing) for item in items] == [
        ("함수 변화율 설명", "100점", "15%", "9월"),
        ("미분 주제 탐구 보고서", "100점", "25%", "8~11월"),
    ]
    assert all(not item.method and not item.rubric_html for item in items)


def test_combined_plan_uses_exact_short_course_heading_boundary() -> None:
    source = """
    수학과 평가계획
    1. 공통수학1
    2. 대수
    3. 기하

    # 공통수학1
    ## 수행평가 세부 계획
    가. 공통수학 탐구
    <table><tr><th>성취기준</th><td>[10공수1-01-01]</td></tr><tr><th>평가방법</th><td>탐구</td></tr></table>

    # 대수
    ## 수행평가 세부 계획
    가. 지수함수 모델링
    <table><tr><th>성취기준</th><td>[12대수01-01]</td></tr><tr><th>평가방법</th><td>보고서</td></tr></table>

    # 기하 (2학기)
    ## 수행평가 세부 계획
    가. 이차곡선 설계
    <table><tr><th>성취기준</th><td>[12기하01-01]</td></tr><tr><th>평가방법</th><td>프로젝트</td></tr></table>
    """

    algebra = parse_assessment_section(source, "대수")

    assert algebra.boundary_status.startswith("subject_heading_exact:")
    assert [item.title for item in algebra.items] == ["지수함수 모델링"]
    assert algebra.items[0].extraction_status == "bounded"
    assert "이차곡선 설계" not in algebra.source_markdown


def test_exact_math_heading_stops_at_a_non_math_course_plan() -> None:
    source = """
    # 공통수학1
    ## 수행평가 세부 계획
    가. 이차함수 문제 해결
    <table><tr><th>성취기준</th><td>[10공수1-02-07]</td></tr>
    <tr><th>평가방법</th><td>서술형</td></tr></table>

    # 2026학년도 1학기 [공통영어1] 교수학습 및 평가 운영 계획
    # 공통영어1
    ## 수행평가 세부 계획
    가. 영어 역할극 영상 제작
    <table><tr><th>성취기준</th><td>[10공영1-02-01]</td></tr></table>
    """

    section = parse_assessment_section(source, "공통수학1")

    assert [item.title for item in section.items] == ["이차함수 문제 해결"]
    assert "영어 역할극" not in section.source_markdown


def test_short_performance_assessment_heading_is_a_block_anchor() -> None:
    source = """
    # 기하
    가. 평가 목적
    평가를 통해 학습을 지원한다.
    라. 수행평가 영역 및 배점
    1) 이차곡선 설계 프로젝트
    <table><tr><th>성취기준</th><td>[12기하01-01]</td></tr><tr><th>평가방법</th><td>프로젝트</td></tr></table>
    마. 결시자 처리 기준
    """

    section = parse_assessment_section(source, "기하")

    assert section.boundary_status == "subject_heading_exact:assessment_anchor"
    assert [item.title for item in section.items] == ["이차곡선 설계 프로젝트"]
    assert section.items[0].extraction_status == "bounded"


def test_pdf_summary_table_rows_become_separate_confirmed_items() -> None:
    source = """
    # 확률과 통계
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 평가 요소 | 배점 | 수행평가 과제 |
    | --- | --- | --- | --- | --- |
    | 서·논술형 | [12확통03-06] | 표본평균 설명 | 100점 | 주제 탐구 프로젝트 |
    | 포트폴리오 | [12확통03-07] | 풀이 과정 기록 | 100점 | 오답 노트 작성 |
    """

    section = parse_assessment_section(source, "확률과 통계")

    assert [item.title for item in section.items] == ["주제 탐구 프로젝트", "오답 노트 작성"]
    assert all(item.extraction_status == "bounded" for item in section.items)
    assert section.items[0].standards == ("[12확통03-06]",)
    assert "오답 노트 작성" not in section.items[0].source_html


def test_summary_table_item_keeps_its_matching_rubric_row() -> None:
    source = """
    # 확률과 통계
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 배점 | 수행평가 과제 |
    | --- | --- | --- | --- |
    | 서·논술형 | [12확통03-06] | 100점 | 주제 탐구 프로젝트 |
    | 포트폴리오 | [12확통03-07] | 100점 | 오답 노트 작성 |

    ### 수행평가 채점 기준
    | 평가과제 | 수행평가 채점 기준 |
    | --- | --- |
    | 주제 탐구 프로젝트 | 자료 분석 근거가 정확하면 100점 |
    | 오답 노트 작성 | 풀이 과정이 충실하면 100점 |
    """

    section = parse_assessment_section(source, "확률과 통계")

    first = next(item for item in section.items if item.title == "주제 탐구 프로젝트")
    assert "자료 분석 근거가 정확하면 100점" in first.rubric_html
    assert "풀이 과정이 충실하면 100점" not in first.rubric_html


def test_rubric_rows_do_not_become_separate_assessment_items() -> None:
    source = """
    # 수학과제 탐구
    ## 수행평가 세부 계획
    | 평가방법 | 성취기준 | 수행평가 과제 |
    | --- | --- | --- |
    | 보고서 | [12수과01-01] | 현상 분석 탐구 보고서 |

    ## 수행평가 채점 기준
    | 평가 항목 | 평가 요소 | 수행 수준 | 배점 |
    | --- | --- | --- | --- |
    | 주제 선정 | 적절성 | 탐구 목적이 분명함 | 10점 |
    | 자료 분석 | 논리성 | 근거가 타당함 | 10점 |
    """

    section = parse_assessment_section(source, "수학과제 탐구")

    assert [item.title for item in section.items] == ["현상 분석 탐구 보고서"]


def test_summary_row_with_another_course_code_is_not_published() -> None:
    source = """
    # 대수
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가방법</th><th>성취기준</th><th>평가과제</th></tr>
      <tr><td>보고서</td><td>[12기하01-01]</td><td>이차곡선 탐구</td></tr>
      <tr><td>보고서</td><td>[12대수01-01]</td><td>지수함수 모델링</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == ["지수함수 모델링"]


def test_expected_code_table_recovers_math_from_headingless_combined_source() -> None:
    source = """
    여러 교과 평가계획
    <table>
      <tr><th>평가 영역명</th><td>영어 역할극</td></tr>
      <tr><th>성취기준</th><td>[10공영1-02-04]</td></tr>
      <tr><th>평가방법</th><td>발표</td></tr>
    </table>
    <table>
      <tr><th>평가 영역명</th><td>지수함수로 미래 예측하기</td></tr>
      <tr><th>성취기준</th><td>[12대수01-01]</td></tr>
      <tr><th>평가방법</th><td>탐구 보고서</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == ["지수함수로 미래 예측하기"]
    assert section.items[0].extraction_status == "bounded"
    assert "영어 역할극" not in section.items[0].source_html


def test_mixed_standard_code_table_is_not_recovered_globally() -> None:
    source = """
    여러 교과 평가계획
    <table>
      <tr><th>평가 영역명</th><td>교과 융합 자료 묶음</td></tr>
      <tr><th>성취기준</th><td>[12대수01-01] [10공영1-02-04]</td></tr>
      <tr><th>평가방법</th><td>보고서</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.extraction_status == "bundle_review"
    assert item.title == "수행평가 원문 구간"


def test_explicit_table_is_recovered_inside_exact_course_without_section_anchor() -> None:
    source = """
    # 수학Ⅱ
    평가 운영 안내
    <table>
      <tr><th>평가 영역명</th><td>문제 해결과정 논술하기</td><th>영역만점</th><td>10점</td></tr>
      <tr><th>수행과제</th><td>논리적인 근거를 제시하여 해결 과정을 설명한다.</td></tr>
      <tr><th>성취기준</th><td>[12수학Ⅱ02-01]</td></tr>
      <tr><th>평가방법</th><td>서·논술형</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "수학Ⅱ")

    assert [item.title for item in section.items] == ["문제 해결과정 논술하기"]
    assert section.items[0].extraction_status == "bounded"


def test_plain_assessment_area_label_is_source_authored_title_evidence() -> None:
    source = """
    # 2026학년도 (인공지능 수학)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>평가영역</th><td>텍스트 자료 처리하기</td><th>영역만점</th><td>20점</td></tr>
      <tr><th>평가요소</th><td>텍스트에서 유용한 정보 찾기 20(점)</td></tr>
      <tr><th>성취기준</th><td>[12인수02-02]</td></tr>
      <tr><th>평가방법</th><td>프로젝트</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "인공지능 수학").items[0]

    assert item.title == "텍스트 자료 처리하기"


def test_area_max_header_recovers_task_name_and_strips_score_suffix() -> None:
    source = """
    # 2026학년도 (수학과제 탐구)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    <table>
      <tr><th>영역(만점)</th><th>평가항목</th><th>평가요소</th>
      <th>채점기준</th><th>배점</th></tr>
      <tr><td>수학과제 탐구보고서 (25)</td><td>주제</td>
      <td>논리성</td><td>타당함</td><td>25</td></tr>
      <tr><th>성취기준</th><td colspan="4">[12수과02-03]</td></tr>
      <tr><th>평가방법</th><td colspan="4">보고서</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "수학과제 탐구").items[0]

    assert item.title == "수학과제 탐구보고서"


def test_summary_matrix_keeps_all_explicit_performance_area_names() -> None:
    source = """
    <table>
      <tr><th>평가 유형</th><td>정기시험</td><td>수행 평가</td>
      <td>수행 평가</td><td>수행 평가</td></tr>
      <tr><th>평가영역</th><td>기말고사</td><td>문제풀이집</td>
      <td>문제해결</td><td>보고서 작성</td></tr>
      <tr><th>평가방법</th><td>선택형</td><td>포트폴리오</td>
      <td>서술형</td><td>보고서</td></tr>
      <tr><th>배점</th><td>100점</td><td>20점</td><td>20점</td><td>20점</td></tr>
    </table>
    """

    assert strict_source_titles(source) == ["문제풀이집", "문제해결", "보고서 작성"]


def test_assessment_matrix_keeps_only_performance_assessment_columns() -> None:
    source = """
    # 공통수학1
    ## 평가의 종류와 반영 비율
    <table>
      <tr><th>평가종류</th><th>정기고사</th><th>정기고사</th><th>수행평가</th><th>수행평가</th></tr>
      <tr><th>반영비율</th><td>30%</td><td>30%</td><td>20%</td><td>20%</td></tr>
      <tr><th>평가영역</th><td>1차 정기고사</td><td>2차 정기고사</td>
      <td>수학 탐구 및 발표</td><td>문제해결 포트폴리오</td></tr>
      <tr><th>만점</th><td>100점</td><td>100점</td><td>100점</td><td>100점</td></tr>
      <tr><th>평가방법</th><td>선택형</td><td>선택형</td><td>탐구 발표</td><td>활동지 작성</td></tr>
      <tr><th>성취기준</th><td></td><td></td><td>[10공수1-01-01]</td><td>[10공수1-02-01]</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "공통수학1")

    assert [item.title for item in section.items] == ["수학 탐구 및 발표", "문제해결 포트폴리오"]
    assert section.items[0].weight == "20%"
    assert section.items[0].method == "탐구 발표"
    assert "1차 정기고사" not in section.items[0].source_html


def test_catalogue_hint_is_used_only_when_the_original_table_cell_confirms_it() -> None:
    source = """
    # 대수
    <table>
      <tr><th>구분</th><th>내용</th></tr>
      <tr><td>수행평가 활동</td><td>하노이 탑 수열 규칙 탐구</td></tr>
      <tr><td>성취기준</td><td>[12대수03-01]</td></tr>
      <tr><td>평가방법</td><td>탐구 보고서</td></tr>
      <tr><td>배점</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(
        source,
        "대수",
        ("하노이 탑 수열 규칙 탐구", "원문에 없는 제목"),
    )

    assert [item.title for item in section.items] == ["하노이 탑 수열 규칙 탐구"]
    assert section.items[0].extraction_status == "bounded"


def test_separates_each_heading_and_keeps_its_own_rubric() -> None:
    source = """
    # 2026학년도 (대수)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준

    가. 지수와 로그 문제해결력 평가(100점 만점, 반영 비율 10%)
    <table>
      <tr><th>성취기준</th><td>[12대수01-01]</td></tr>
      <tr><th>평가개요</th><td>지수와 로그 문제의 풀이 과정을 평가한다.</td></tr>
      <tr><th>평가 방법</th><td>논·서술형</td></tr>
      <tr><th>평가영역</th><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>문제해결</td><td>논리</td><td>과정이 정확함</td><td>10점</td></tr>
    </table>

    나. 삼각함수 문제해결력 평가(100점 만점, 반영 비율 10%)
    <table>
      <tr><th>성취기준</th><td>[12대수02-01]</td></tr>
      <tr><th>평가개요</th><td>삼각함수 문제의 풀이 과정을 평가한다.</td></tr>
      <tr><th>평가 방법</th><td>논·서술형</td></tr>
      <tr><th>평가요소</th><th>세부기준</th><th>부여점수</th></tr>
      <tr><td>표현</td><td>그래프가 정확함</td><td>10점</td></tr>
    </table>

    # 7. 결시자와 학적 변동자 처리 기준
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == [
        "지수와 로그 문제해결력 평가",
        "삼각함수 문제해결력 평가",
    ]
    assert section.items[0].overview == "지수와 로그 문제의 풀이 과정을 평가한다."
    assert section.items[0].standards == ("[12대수01-01]",)
    assert "과정이 정확함" in section.items[0].rubric_html
    assert "그래프가 정확함" not in section.items[0].rubric_html
    assert "그래프가 정확함" in section.items[1].rubric_html


def test_explicit_area_name_replaces_a_structural_numbered_heading() -> None:
    source = """
    # 2025학년도 (수학Ⅱ)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준
    1) 교육과정 성취기준 및 평가기준, 평가 요소 및 배점
    <table>
      <tr><th>평가 영역명</th><td>미분을 활용하여 함수 그래프 그리기</td>
      <th>영역만점</th><td>15점</td></tr>
      <tr><th>수행과제</th><td>함수의 증가와 감소를 설명한다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>그래프</td><td>개형이 정확함</td><td>15점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "수학Ⅱ").items[0]

    assert item.title == "미분을 활용하여 함수 그래프 그리기"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"
    assert item.score == "15점"


def test_explicit_task_field_replaces_a_generic_process_assessment_heading() -> None:
    source = """
    # 2026학년도 (대수)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    다. 학습과정평가
    <table>
      <tr><th>평가 영역명</th><td>학습과정평가</td><th>영역만점</th><td>10점</td></tr>
      <tr><th>수행과제</th><td>학습과정 포트폴리오(수업 필기 및 문제풀이 정리)</td></tr>
      <tr><th>성취기준</th><td>[12대수01-01]</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>정리</td><td>근거가 타당함</td><td>10점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.title == "학습과정 포트폴리오(수업 필기 및 문제풀이 정리)"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"


@pytest.mark.parametrize(
    "name_label", ["평가영역명3", "평가 영역명 12", "수행평가명", "과제명"]
)
@pytest.mark.parametrize("format", ["html", "markdown"])
def test_named_task_label_outranks_an_earlier_plain_task_description(
    name_label: str, format: str
) -> None:
    description = "실생활 자료를 수집하여 함수로 표현하고 변화 양상을 분석하는 보고서 작성하기"
    title = "실생활 자료의 함수 모델링 탐구"
    rows = [
        ("수행과제", description),
        (name_label, title),
        ("성취기준", "[12대수01-01]"),
        ("평가방법", "프로젝트"),
    ]
    if format == "html":
        source = "<table>" + "".join(
            f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows
        ) + "</table>"
    else:
        source = "| 항목 | 내용 |\n| --- | --- |\n" + "\n".join(
            f"| {label} | {value} |" for label, value in rows
        )

    assert explicit_segment_title(source) == title


def test_plain_task_description_does_not_overwrite_real_lettered_headings_or_duplicate_items():
    first_description = "이차곡선과 공간도형의 정의를 활용하여 해결 과정을 논리적으로 설명하기"
    second_description = "단원별 핵심 개념을 정리하고 문제 해결 과정을 기록하여 제출하기"
    source = f"""
    # 2026학년도 (기하)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 기준
    가. 기하 원리의 논증
    <table>
      <tr><th>수행과제</th><td>{first_description}</td></tr>
      <tr><th>성취기준</th><td>[12기하01-01]</td></tr>
      <tr><th>평가방법</th><td>논술</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>논증</td><td>정당화 과정이 타당함</td><td>15점</td></tr>
    </table>
    나. 개념 포트폴리오
    <table>
      <tr><th>수행과제</th><td>{second_description}</td></tr>
      <tr><th>성취기준</th><td>[12기하03-01]</td></tr>
      <tr><th>평가방법</th><td>포트폴리오</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>개념</td><td>개념의 관계가 정확함</td><td>10점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "기하")
    public = [item for item in section.items if item.extraction_status == "bounded"]

    assert [item.title for item in public] == ["기하 원리의 논증", "개념 포트폴리오"]
    assert all(item.title_basis == "heading" for item in public)
    assert first_description in public[0].source_html
    assert second_description in public[1].source_html
    assert "개념의 관계가 정확함" not in public[0].rubric_html
    assert "개념의 관계가 정확함" in public[1].rubric_html


@pytest.mark.parametrize("name_label", ["평가영역명", "평가영역명3"])
@pytest.mark.parametrize(
    "heading", ["가. 개념 정리 활동", "1) 교육과정 성취기준 및 평가기준, 평가 요소 및 배점"]
)
def test_separate_description_table_does_not_add_a_second_task_before_named_table(
    name_label, heading
):
    description = "핵심 개념을 구조화하고 대표 문제의 단계별 해결 과정을 체계적으로 기록하기"
    source = f"""
    # 2026학년도 (공통수학2)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 기준
    {heading}
    <table>
      <tr><th>수행과제</th><td>{description}</td></tr>
      <tr><th>성취기준</th><td>[10공수2-01-01]</td></tr>
      <tr><th>평가방법</th><td>포트폴리오</td></tr>
    </table>
    <table>
      <tr><th>{name_label}</th><td>수학 개념의 연결과 구조화</td><th>영역만점</th><td>20점</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>구조화</td><td>관계가 명확함</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "공통수학2")
    public = [item for item in section.items if item.extraction_status == "bounded"]

    assert len(public) == 1
    assert public[0].title == "수학 개념의 연결과 구조화"
    assert public[0].title_basis == "table"
    assert description in public[0].source_html
    assert "관계가 명확함" in public[0].rubric_html


def test_long_source_authored_name_is_preserved_without_a_new_length_heuristic():
    title = (
        "생활 속 자료를 함수의 개념 및 그래프로 연결하고 수학적 근거에 따라 "
        "여러 해석의 타당성을 비교하여 설명하는 융합 탐구 보고서"
    )
    assert len(title) > 60
    source = (
        "<table><tr><th>수행과제</th><td>자료를 분석하여 보고서 작성하기</td></tr>"
        f"<tr><th>수행평가명</th><td>{title}</td></tr></table>"
    )

    assert explicit_segment_title(source) == title
    assert explicit_segment_title(
        f"<table><tr><th>수행과제</th><td>{title}</td></tr></table>"
    ) == title


def test_long_task_instruction_does_not_replace_the_source_heading_as_a_title() -> None:
    source = """
    # 2026학년도 (공통수학1)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    나. 생활 속 주제 탐구
    <table>
      <tr><th>수행 과제</th><td>공통수학1에서 배우는 다항식, 방정식과 부등식,
      경우의 수, 행렬과 관련하여 자유롭게 주제를 선정하여 보고서 작성하기.</td></tr>
      <tr><th>성취기준</th><td>[10공수1-01-01]</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>주제 선정</td><td>근거가 타당함</td><td>100점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "공통수학1").items[0]

    assert item.title == "생활 속 주제 탐구"
    assert item.title_basis == "heading"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (
            "4. 수행평가 세부 계획<br>가. 수학 독서 글쓰기(50%)",
            "수학 독서 글쓰기",
        ),
        (
            "6. 수행평가 세부기준<br>가. 수행평가 1: 이차곡선의 활용 탐구보고서(논술형)",
            "이차곡선의 활용 탐구보고서(논술형)",
        ),
        ("4. 포트폴리오 수행평가 기준", "포트폴리오"),
        ("4. 수행평가 영역1 : 서술형 평가", "서술형 평가"),
        ("4. 문제 해결 평가 기준", "문제 해결"),
        (
            "4. 포트폴리오 평가 (평가시기 : 3~6월 수시평가): 20점, 기본점수: 0점",
            "포트폴리오 평가",
        ),
        (
            "4. [서·논술형] 창의융합 프로젝트(평가시기: 6월) : 10점, 기본점수: 1점",
            "창의융합 프로젝트",
        ),
        (
            "4. 주제탐구1,2(25%, 25점): 단원에서 학습한 내용을 바탕으로 탐구함.",
            "주제탐구1,2",
        ),
        (
            "4. 수행평가 세부기준 (가) 주제탐구 독서감상문",
            "주제탐구 독서감상문",
        ),
        (
            "4. 4순위(학기말 반영 비율): 학습활동지 포트폴리오를 통한 대수 원리 내면화",
            "학습활동지 포트폴리오를 통한 대수 원리 내면화",
        ),
    ],
)
def test_embedded_task_name_is_separated_from_the_structural_heading(
    heading: str, expected: str
) -> None:
    source = f"""
    # 2026학년도 (대수) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    {heading}
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == [expected]
    assert section.items[0].title_basis == "heading"
    assert section.items[0].extraction_status == "bounded"


def test_structural_subheading_is_not_published_as_an_assessment_name() -> None:
    source = """
    # 2026학년도 (대수)과 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 기준
    가. 평가 개요
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>탐구</td><td>근거가 정확함</td><td>20점</td></tr>
    </table>
    나. 채점기준표
    <table><tr><th>평가 항목</th><th>채점기준</th><th>점수</th></tr></table>
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == ["수행평가 원문 구간"]
    assert all(item.extraction_status == "bundle_review" for item in section.items)
    assert section.detected_titles == ()


@pytest.mark.parametrize(
    "title",
    [
        "교육과정 성취기준 : [12대수01-01] ~ [12대수03-07]",
        "[12기하01-01] ~ [12기하03-07]",
        (
            "동일학년 동일교과를 2인 이상의 교사가 지도할 경우 "
            "수행평가 영역 및 배점을 같게 할 수 있다."
        ),
        "신체장애 학생이 특정 영역의 수행평가가 불가능한 경우 인정점을 부여할 수 있다.",
        "채점기준표 ‣ 다양한 실생활 자료에 녹아있는 수학적 사실을 설명할 수 있다.",
        "수행평가 결시자의 성적처리는 별도의 평가 기간을 정해 재평가하는 것을 원칙으로 한다.",
        "전·편입생은 다음과 같이 처리한다.",
        "질병 및 인정 결석으로 참여하지 못한 경우 추가평가의 기회를 부여한다.",
        "특수교육 대상자 및 기타 사항에 대하여는 본교 학업성적관리규정에 따른다.",
        "수행평가를 할 때 표절 행위가 발생하지 않도록 사전 교육을 충분히 실시한다.",
        "AI는 수업·평가에서 보조적으로 활용할 수 있으나 공정성을 훼손하지 않도록 유의한다.",
        "AI의 활용을 허용하는 경우에는 AI 활용 범위에 대한 구체적 기준을 마련한다.",
        "AI를 활용한 경우 활동지의 AI 활용 내역란에 도구와 목적을 반드시 기록한다.",
        "출제 원안에는 문항별 배점을 모두 표기하며 100점 만점으로 한다.",
        "영역 만점은 20점으로 한다.",
        (
            "수행평가 결시자의 성적처리는 별도의 평가 기간을 정해 재평가하는 것을 "
            "원칙으로 한다. 단, 질병 장기"
        ),
        "수행평가 영역별 특성에 따른 배점 비율의 적정성을 유지하고 상세한 채점 기준을 마련",
        "영역의 특성, 평가 목표, 평가 내용, 평가 상황 등을 고려하여 선다형 평가를 실시",
        "질병 및 인정 결석으로 참여하지 못한 경우 추가평가의 기회를 부여한다. 단, 응하지",
        (
            "특수교육 대상자 및 기타 사항에 대하여는 본교 학업성적관리규정에 따르고 "
            "교과협의회를 통하여"
        ),
        "수행평가의 목표, 영역, 횟수, 배점에 관한 세부기준은 수행평가 세부계획",
        (
            "수행평가를 할 때 표절 행위가 발생하지 않도록 사전 교육을 충분히 실시하고 "
            "표절이 의심되는 경우"
        ),
        "수행평가는 교과 담당교사가 교과 수업시간에 학생의 수행 과정 및 결과를 직접 관찰하고",
        "AI는 수업·평가에서 보조적으로 활용할 수 있으나 공정성을 훼손하지 않도록 유의",
        "AI의 활용을 허용하는 경우에는 AI 활용 범위에 대한 구체적 기준을 마련하고 유의",
        "수행평가 인공지능(AI) 도구 활용 시 평가 시행 전 학생 유의 사항을 안내하고",
        "교과의 특성을 고려하여 수행평가의 영역·방법·횟수·세부 기준과 반영 비율을 정하고",
        "AI를 활용한 경우 활동지의 AI 활용 내역란에 도구와 목적을 반드시 기록",
        "수행평가 결과물은 학생 개개인의 피드백을 위해 개인에게 돌려주어 학습에 활용하도록",
        "전입생이 실시한 수행평가는 교과협의회를 통해 본교 수행평가로 인정하거나 재실시",
        "성취기준에 근거한 평가의 영역·요소·방법·횟수·세부기준·반영비율 등 구체적인 방법은",
        (
            "정기시험은 문항별 배점을 표시하여 가급적 100점 만점으로 출제한다. "
            "또한 다양한 성취수준을 판별할"
        ),
        "정기시험에서 평가할 성취기준, 성취기준별 성취수준, 영역별 성취수준, 학기 단위 성취",
        "내용 영역, 성취기준, 난이도, 정답, 문항별 배점 및 채점기준이 명시된 문항정보표를 작성",
        "모둠토의와 협력활동 시간에 AI를 활용하여 자신의 의견을 대체하는 행위 금지",
        "포트폴리오에서 수학적으로 오류가 발견되면 완성하여 제출한 것으로 보지 않는다.",
        "성취기준별 성취수준에 따른 수행 정도의 차이를 반영한 채점 기준 개발",
        "정리한 개념과 사례를 접목하여 풀이과정을 서술함.",
        "비고 : 매 수업 활동 참여도가 부족한 경우 1점씩 감점한다.",
        "평가요소: 흥미, 성취동기, 수업 준비, 참여",
        "결석의 경우 결석 사유 소멸 후 1주일 이내로 평가한다.",
        "수행평가 시간에 결석이나 조퇴로 출석하지 않은 학생은 추가 기회를 주고",
        "수행평가의 반영 비율은 학기 단위 성적의 30% 이상으로 하되 타당도를 확보",
        "학생이 성취기준에 도달한 정도와 이를 판단한 근거 및 흥미와 성취욕구를 기록",
        "원안 제출 시 정답과 문항별 배점 및 채점기준이 명시된 문항정보표를 함께 제출",
        "문제를 해결하는 과정과 절차를 논리적으로 수행하였는가?",
        "수학 학습 의지와 끈기를 갖고 성실히 활동을 수행하였는가?",
        "수행평가 세부 계획과 채점 기준 및 배점을 사전에 안내하고 학생에게 설명",
        "결석의 경우 결석 사유 소멸 후 1주일 이내로 평가하고 미응시한 것으로 처리",
        "객관적이고 공정한 채점 기준을 세워 평가실시 전 평가 영역별 기준을 안내",
        "모든 출제 원안에는 문항별로 배점을 표시하되 평가의 변별력을 높이도록",
        "결시생, 재입학, 전·편입생 및 특수교육대상자의 성적 처리",
        "결시(인정결, 병결)로 인한 수행평가 결시자에게 추가 응시 기회를 부여",
        "심화 탐구하면서 느낀 점 또는 향후 학습계획을 명확하게 밝히고 있는가?",
        "수행평가에 참여한 학생에게 기본적으로 부여하는 최소 점수를 의미함.",
        "5지 선다형과 서·논술형 등 성취기준의 도달 여부를 확인할 문항으로 출제",
        "평가(정기시험 및 수행평가)의 영역, 요소, 방법, 시기, 횟수, 반영비율",
        "성취기준을 분석하여 적합한 평가 요소를 도출하고 성취수준을 판별",
        "학생의 수업 시간 활동 및 내용을 작성하여 기록",
        "안내된 절차에 따라 좌표공간에서 두 점 사이의 거리를 구",
        "학생의 학습 활동에 대한 효과를 높이고 학습 활동 중 오류를 확인하여",
        "수행평가 세부계획에 의거, 학생들의 수행 과정과 결과를 평가하고",
        "평가의 결과는 차후 평가 계획 수립에 반영하고 교수학습을 개선",
        "• 학습자의 학업 및 인성지도, 상담자료로 활용 • 평가 결과 기록",
    ],
)
def test_policy_and_standard_headings_are_structural(title: str) -> None:
    assert heading_title_is_structural(title)


@pytest.mark.parametrize(
    "title",
    ["5\x01. 수행평가 세부기준", "6\x01. 정의적 능력 평가", "7\x01. 성취기준별 성취수준"],
)
def test_legacy_outline_control_bytes_do_not_create_task_titles(title: str) -> None:
    assert heading_title_is_structural(title)


@pytest.mark.parametrize(
    "heading",
    [
        "수행평가 과제별 세부 계획",
        "평가방법 및 채점기준 배점",
        "채점기준 및 배점",
        "질병 결석으로 추가 평가가 불가능한 경우는 본교 규정에 따라 처리",
        "실시 시기 및 횟수",
        "성취기준별 성취수준",
        "평가관점·요소",
        "수행수준 (채점기준) 및 배점",
        "세부내용 및 평가척도표",
        "세부기준",
        "수행평가 개요",
        "수행평가 영역별 평가 요소 및 채점 기준",
        "평가 요소 및 성취 기준",
        "동점자 처리 기준",
        "피드백 및 기록",
        "수행평가 분할점수",
        "수행평가 영역 및 배점",
        "관련 성취기준",
        "평가 방법 및 결과의 활용",
        "수행평가 영역별 성취기준 및 평가 척도",
        "평가 영역별 세부 채점 기준",
        "평가 유의사항",
        "수행평가 성취율과 원점수",
        "정의적 능력 평가 세부 사항",
        "정의적 능력 평가",
        "정의적 영역 평가",
        "정의적 능력 평가의 실제",
        "사회정서학습 연계 정의적 능력 평가",
        "학습과정평가",
        "수학학습과정평가",
        "서·논술형 평가 계획",
        "서술·논술형 평가",
        "공통 유의사항",
        "[유의사항]",
        "영역별 세부 평가 기준",
        "성취 기준과 평가기준",
        "평가 과제",
        "세부 채점 기준",
        "평가 항목과 배점",
        "정의적 능력 평가 계획",
        "수행평가 세부기준(영역별 배점과 채점 기준)",
        "수행평가 분할 점수 산출",
        "영역별 평가 방법과 채점 기준",
        "평가 영역 및 배점",
        "평가방법 및 내용",
        "성취기준 및 평가 방법",
        "평가 영역별 반영 비율",
        "정기시험 및 수행평가 세부계획",
        "기타 사항",
        "정의적 능력 평가 요소와 평가 방법",
        "평가과제1",
        "수행과제2",
        "평가영역1",
        "수행 1",
        "항목별 계획",
        "평가 영역",
        "평가 요소별 세부 채점 기준",
        "평가 항목별 채점 기준",
        "기본 점수 부여 여부 및 방법",
        "평가 방법 및 활용",
        "4. 고사별 배점",
        "수행평가의 세부 기준 (평가 과제별로 작성)",
        "수행 평가 세부기준 및 배점",
        "수행 평가 세부 계획",
        "수업참여도 세부기준",
        "방침",
        "수행평가 과제별 개요",
        "수행평가 범위와 기준",
        "평가 과제별 세부 계획",
        "AI 활용 금지 범위",
        "수행평가 인정점 산출 기준",
        "수행평가 평가 기준",
        "과정중심 수행평가 세부 계획",
        "평가 방법 및 반영 비율",
        "수업 계획",
        "수행평가 영역 및 평가항목, 배점 및 채점기준",
        "수행평가 요소 및 성취 기준",
        "평가과제별 반영 비율 및 성취수준",
        "평가과제별 채점 기준",
        "수행평가 1",
        "수행평가1",
        "세부 평가 내용",
        "평가 방법 및 평가내용",
        "정기 시험 세부계획",
        "과제별 배점",
        "최종 배점",
        "수행평가 내용 및 평가 세부 기준",
        "수행평가 인정점 부여 기준",
        "수행평가 세부 기준(영역별 배점 및 채점기준)",
        "수행 평가 세부 계획 ※ 과목 특성에 따라 양식 변경",
        "기본 방향",
        "평가 방법과 반영 비율",
        "수행 평가 세부 계획 (교과 사정에 따라 변경될 수 있음.)",
        "수행평가 세부 계획(1)",
        "항목별 평가 기준",
        "통계",
        "벡터",
        "행렬",
        "수행평가 세부 계획(평가과제별로 작성)",
        "평가 요소 : 흥미와 자신감",
        "최하 3점부터 최고 20점까지 0.5점 급간으로 점수를 부여하며 세부 내용은 아래와 같다.",
        "공교육 정상화 촉진 및 선행교육 규제에 관한 특별법에 따라 학생이 배운 범위만 평가",
        (
            "수행평가 결과물에 AI 활용 여부와 활용 목적을 간단히 기록하여야 하며 "
            "AI가 생성한 내용을 그대로 제출하면 불이익을 받을 수 있음."
        ),
        "학기 단위 성취수준 설정,",
        "학기 단위 성취수준 설정 13. 최소 성취수준 설정(공통과목)",
        "일반사항",
        "영역별",
        "문제 해결 과정에서 막히는 부분에 한하여 힌트 요청할 때, AI 활용 가능",
        "평가 관련 제반 문제는 교과협의회에서 협의하고, 주요 결정 사항은 심의한다.",
        "평소 수업 활동이 자연스럽게 평가로 이어지도록 계획한다.",
    ],
)
def test_field_and_policy_headings_do_not_become_assessment_titles(heading: str) -> None:
    source = f"""
    # 2026학년도 (대수) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. {heading}
    <table>
      <tr><th>반영비율</th><td>20%</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    section = parse_assessment_section(source, "대수")

    assert all(item.title != heading for item in section.items)
    assert all(item.extraction_status != "bounded" for item in section.items)


def test_strict_title_scan_keeps_outer_rows_and_ignores_nested_rubric_cells() -> None:
    source = """
    <table>
      <tr><th>영역</th><th>평가 내용</th><th>반영비율</th><th>평가 기준</th><th>배점</th></tr>
      <tr><td>함수 그래프 탐구 보고서</td><td>[12미적Ⅰ01-01]</td><td>20%</td>
      <td><table><tr><th>완성도</th></tr><tr><td>활동 소감 쓰기</td></tr></table></td>
      <td>100</td></tr>
      <tr><td>변화율 모델링 포트폴리오</td><td>[12미적Ⅰ02-01]</td><td>20%</td>
      <td>과정 평가</td><td>100</td></tr>
    </table>
    """

    assert strict_source_titles(source) == [
        "함수 그래프 탐구 보고서",
        "변화율 모델링 포트폴리오",
    ]


def test_strict_title_scan_reads_performance_columns_not_absence_policy() -> None:
    source = """
    <table>
      <tr><th>평가종류</th><th colspan="2">정기시험</th><th colspan="2">수행평가</th></tr>
      <tr><td colspan="3">영역 중간고사</td><td>주제 탐구 프로젝트</td>
      <td>문제 해결력 포트폴리오</td></tr>
    </table>
    <table><tr><th>수행평가 영역</th><th>결시자 처리기준</th></tr></table>
    """

    assert strict_source_titles(source) == [
        "주제 탐구 프로젝트",
        "문제 해결력 포트폴리오",
    ]


def test_strict_title_scan_reads_summary_row_labelled_count_and_area() -> None:
    source = """
    <table>
      <tr><th>평가 유형</th><th colspan="2">정기시험</th><th colspan="2">수행평가</th></tr>
      <tr><td>횟수/영역</td><td>1차</td><td>2차</td>
      <td>이차함수 실생활 문제해결하기</td><td>수학 탐구 학습 노트 작성하기</td></tr>
    </table>
    """

    assert strict_source_titles(source) == [
        "이차함수 실생활 문제해결하기",
        "수학 탐구 학습 노트 작성하기",
    ]


def test_detected_title_list_removes_duplicates_without_changing_source_order() -> None:
    assert deduplicate_titles(
        ["주제 탐구 프로젝트", "주제 탐구 프로젝트", "문제 해결력 포트폴리오"]
    ) == ["주제 탐구 프로젝트", "문제 해결력 포트폴리오"]


@pytest.mark.parametrize(
    "title",
    [
        "수행평가 과제별 세부 계획",
        "평가방법 및 채점기준 배점",
        "채점기준 및 배점",
        (
            "공통수학1에서 배우는 다항식, 방정식과 부등식, 경우의 수, 행렬과 관련하여 "
            "자유롭게 주제를 선정하여 보고서 작성하기."
        ),
    ],
)
def test_repair_does_not_treat_field_labels_as_credible_titles(title: str) -> None:
    assert not credible_title(title)


def test_curriculum_unit_with_only_achievement_levels_is_not_a_task() -> None:
    source = """
    # 2026학년도 (공통수학1) 교수학습 및 평가 운영 계획
    ## 6. 성취기준별 평가 기준
    (1) 다항식
    <table>
      <tr><th>성취기준</th><th>성취기준별 평가 기준</th></tr>
      <tr><td>[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.</td><td>A 매우 우수함</td></tr>
    </table>
    ## 7. 수행평가 세부 계획
    """

    section = parse_assessment_section(source, "공통수학1")

    assert all(item.title != "다항식" for item in section.items)
    assert all(item.extraction_status != "bounded" for item in section.items)


def test_explicit_table_name_outweighs_a_generic_numbered_heading() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가 운영 계획
    ## 6. 수행평가 세부 계획
    1. 수열
    <table>
      <tr><th>평가영역명</th><td>수열의 규칙을 활용한 모델링 탐구</td>
      <th>영역만점</th><td>20점</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>모델링</td><td>근거가 타당함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.title == "수열의 규칙을 활용한 모델링 탐구"
    assert item.title_basis == "table"
    assert item.extraction_status == "bounded"


def test_explicit_table_title_preserves_source_roman_numeral_spelling() -> None:
    source = """
    # 2026학년도 (공통수학1) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. 원리의 적용과 해석Ⅰ(11점)
    <table>
      <tr><th>평가 영역명</th><td>원리의 적용과 해석Ⅰ</td></tr>
      <tr><th>수행 과제</th><td>수학 포트폴리오</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>해석</td><td>근거가 타당함</td><td>11점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "공통수학1").items[0]

    assert item.title == "원리의 적용과 해석Ⅰ"
    assert item.title_raw == "원리의 적용과 해석Ⅰ"


def test_explicit_table_title_trims_merged_score_and_semester_metadata() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    가. 수행평가 세부 기준
    <table>
      <tr><th>평가 영역명</th><td>수학적 모델링 영역 만점 15점 학기 1학기</td></tr>
      <tr><th>수행 과제</th><td>실생활 자료를 함수로 나타내기</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>모델</td><td>근거가 타당함</td><td>15점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.title == "수학적 모델링"
    assert item.title_raw == "수학적 모델링"


def test_short_subject_mention_cannot_publish_another_courses_rubric() -> None:
    source = """
    # 2026학년도 (대수)
    ## 수행평가 세부 기준
    2) 세부 시행 계획 및 채점 기준
    <table>
      <tr><th>평가영역명</th><td>듣기 기반 담화 구성</td></tr>
      <tr><th>성취기준</th><td>[12실영01-01] 핵심 정보를 파악한다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>듣기</td><td>정확함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.title == "수행평가 원문 구간"
    assert item.extraction_status == "source_mismatch_review"
    assert item.overview == ""
    assert item.standards == ()


def test_roman_numeral_standard_code_confirms_the_requested_course() -> None:
    source = """
    # 2025학년도 (수학Ⅱ)
    ## 수행평가 세부 기준
    가. 함수의 극한 문제 해결
    <table>
      <tr><th>성취기준</th><td>[12수학Ⅱ01-01] 함수의 극한의 뜻을 안다.</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>극한</td><td>풀이가 정확함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "수학Ⅱ").items[0]

    assert item.extraction_status == "bounded"
    assert item.title == "함수의 극한 문제 해결"


def test_keeps_rowspan_and_colspan_in_safe_source_html() -> None:
    source = """
    # 2026학년도 (미적분Ⅰ)과 교수학습 및 평가 운영 계획
    ## 수행평가 세부 계획
    1. 변화율 모델링 탐구
    <table onclick="alert(1)">
      <tr><th rowspan="2">평가요소</th><th colspan="2">채점 기준</th></tr>
      <tr><td>설명</td><td>점수</td></tr>
      <tr><td>모델</td><td><script>bad()</script>타당함</td><td>20점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "미적분Ⅰ").items[0]

    assert 'rowspan="2"' in item.source_html
    assert 'colspan="2"' in item.source_html
    assert "onclick" not in item.source_html
    assert "<script" not in item.source_html
    assert "타당함" in item.source_html


def test_unbounded_document_is_one_honest_bundle() -> None:
    source = """
    # 2026학년도 (기하)과 교수학습 및 평가 운영 계획
    <table>
      <tr><th>평가 일시(횟수)</th><th>만점</th><th>반영 비율</th>
      <th>평가 내용</th><th>평가 방법</th></tr>
      <tr><td>4월</td><td>30점</td><td>30%</td>
      <td>이차곡선 탐구 보고서</td><td>보고서 평가</td></tr>
    </table>
    수행평가의 채점 기준과 평가 방법은 다음과 같다.
    """

    item = parse_assessment_section(source, "기하").items[0]

    assert item.extraction_status == "bundle_review"
    assert item.title == "이차곡선 탐구 보고서"
    assert "이차곡선 탐구 보고서" in item.source_html


def test_uncertain_multi_title_bundle_does_not_publish_mixed_summary_values() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    | 수행평가명 | 반영비율 | 만점 |
    | --- | --- | --- |
    | 지수 탐구 | 20% | 100점 |
    | 수열 발표 | 20% | 100점 |
    수행평가 자료와 채점 기준을 안내한다.
    """

    section = parse_assessment_section(source, "대수")
    item = section.items[0]

    assert item.title == "수행평가 원문 구간"
    assert item.extraction_status == "bundle_review"
    assert item.weight == ""
    assert item.score == ""
    assert section.detected_titles == ()
    assert "지수 탐구" in item.source_html
    assert "수열 발표" in item.source_html


def test_rejects_previous_context_jump_artifacts() -> None:
    source = "# 대수 교수학습 및 평가 운영 계획\n[...문맥 전환...]"

    try:
        parse_assessment_section(source, "대수")
    except ValueError as exc:
        assert "context-jump" in str(exc)
    else:
        raise AssertionError("context-jump marker must fail the lossless parser")


def test_markdown_pipe_table_becomes_accessible_html_table() -> None:
    rendered = markdown_fragment_to_html("| 평가영역 | 반영비율 |\n| --- | --- |\n| 모델링 | 20% |")

    assert "<thead>" in rendered
    assert "<th>평가영역</th>" in rendered
    assert "<td>20%</td>" in rendered


def test_zip_member_boundary_keeps_only_the_requested_subject() -> None:
    source = """
    [zip:2학년/2026학년도 화학 평가계획.hwp][ok]
    # 2026학년도 (화학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 기체의 분자량 구하기
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>실험</td><td>타당함</td><td>20점</td></tr></table>

    [zip:2학년/2026학년도 2학년 1학기 대수 평가계획.hwp][ok]
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 생활 속 데이터의 주기성 분석 및 함수 만들기
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>모델링</td><td>타당함</td><td>30점</td></tr></table>
    ### 결시자 처리 기준

    [zip:2학년/2026학년도 영어 평가계획.hwp][ok]
    # 2026학년도 (영어) 교수학습 및 평가계획
    """

    section = parse_assessment_section(source, "대수")

    assert section.boundary_status.startswith("zip_member_subject:")
    assert [item.title for item in section.items] == ["생활 속 데이터의 주기성 분석 및 함수 만들기"]
    assert "기체의 분자량" not in section.source_markdown
    assert "영어" not in section.source_markdown


def test_zip_member_prefers_exact_math_filename_over_economic_math() -> None:
    source = """
    [zip:3학년/2025학년도 경제 수학 평가계획.hwp][ok]
    # 2025학년도 (경제 수학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 경제지표 탐구
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>분석</td><td>타당함</td><td>20점</td></tr></table>

    [zip:1학년/2025학년도 수학 평가계획.hwp][ok]
    # 2025학년도 (수학) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 방정식 문제해결
    <table><tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
    <tr><td>풀이</td><td>정확함</td><td>20점</td></tr></table>
    """

    section = parse_assessment_section(source, "수학")

    assert [item.title for item in section.items] == ["방정식 문제해결"]
    assert "경제지표" not in section.source_markdown


def test_numbered_cells_in_markdown_table_are_not_item_headings() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 함수 모델링 탐구
    | 평가요소 | 채점기준 | 점수 |
    | --- | --- | --- |
    | 1. 수학적 타당성 | 근거가 정확함 | 20점 |
    | 2. 의사소통 | 설명이 명확함 | 10점 |
    ### 결시자 처리 기준
    """

    section = parse_assessment_section(source, "대수")

    assert [item.title for item in section.items] == ["함수 모델링 탐구"]


def test_pdf_style_pipe_table_populates_exact_fields_and_rubric() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 생활 자료 함수 모델링
    | 평가시기 | 반영비율 | 영역만점 | 평가방법 |
    | --- | --- | --- | --- |
    | 5월 2주 | 30% | 100점 | 프로젝트 |

    | 평가요소 | 채점기준 | 척도(배점) |
    | --- | --- | --- |
    | 모델의 타당성 | 근거가 정확함 | 30점 |
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.timing == "5월 2주"
    assert item.weight == "30%"
    assert item.score == "100점"
    assert item.method == "프로젝트"
    assert "근거가 정확함" in item.rubric_html
    assert "<table>" in item.rubric_html


def test_wide_merged_pdf_row_stops_each_value_at_the_next_field_label() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 데이터 주기성 분석
    | 성취기준 | 내용 |  |  |  |  |  |  |  |  |  |  |  |
    | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
    | 평가시기 | 3월 4주-6월 3주 | 반영비율 |  |  | 20% |  |  | 영역만점 |  |  | 100점 |  |
    | 평가 방법 | ☑ 서술･논술 |  | □ 구술･발표 |  |  | □ 토의･토론 |  |  |  | ☑ 프로젝트 |  |  |
    | 평가요소 | 지수와 로그 |  |  |  |  |  |  |  |  |  |  |  |
    | 채점요소 | 채점기준 |  |  |  |  |  |  |  |  |  |  | 척도(배점) |
    | 모델링 | 함수가 타당함 |  |  |  |  |  |  |  |  |  |  | 20점 |
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.timing == "3월 4주-6월 3주"
    assert item.weight == "20%"
    assert item.score == "100점"
    assert item.method == "서술·논술 · 프로젝트"


def test_hwp_expanded_metadata_row_keeps_only_field_shaped_values() -> None:
    source = """
    # 2026학년도 (미적분) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 삼각함수의 도함수 증명하기
    <table>
      <tr><th>평가영역 (단원)</th><td colspan="5">여러 가지 함수의 미분</td>
          <th>시기</th><th>만점 5월 (반영비율)</th><td>100점 (16%)</td></tr>
      <tr><th>평가방법</th><th>유형</th><td colspan="2">gfedcb 서술·논술</td>
          <td>gfedc 구술·발표</td><td>gfedc 프로젝트</td></tr>
      <tr><th>평가방법</th><th>주체</th><td>gfedcb 교사평가</td>
          <td>gfedc 동료평가</td><td>gfedc 자기평가</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>증명</td><td>논리적으로 정확함</td><td>20점</td></tr>
    </table>
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "미적분").items[0]

    assert item.timing == "5월"
    assert item.score == "100점"
    assert item.weight == "16%"
    assert item.method == "서술·논술 · 교사평가"


def test_score_and_weight_do_not_absorb_rubric_or_student_record_example() -> None:
    source = """
    # 2026학년도 (공통수학1) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 수학적 가치 발견을 위한 주제별 자율 탐구 활동
    <table>
      <tr><th>평가 과제명</th>
          <td colspan="5">수학적 가치 발견을 위한 주제별 자율 탐구 활동</td></tr>
      <tr><th>평가방법</th><td>■ 서술·논술</td><td>□ 구술·발표</td>
          <td>■ 조사·관찰보고서</td></tr>
      <tr><th>평가시기</th><td>6월</td><th>반영비율</th><td>20 %</td>
          <th>만점</th><td>20 점</td></tr>
      <tr><th>세특기재 예시</th>
          <td colspan="5">이차함수의 최댓값과 최솟값을 탐구하고 발표함.</td></tr>
    </table>
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "공통수학1").items[0]

    assert item.timing == "6월"
    assert item.weight == "20%"
    assert item.score == "20점"
    assert item.method == "서술·논술 · 조사·관찰보고서"
    assert "이차함수" not in item.score
    assert "이차함수" not in item.weight


def test_checked_method_variants_drop_converter_controls_and_unchecked_options() -> None:
    source = """
    # 2026학년도 (인공지능 수학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 데이터 기반 미래 예측
    <table>
      <tr><th>평가방법</th><td>☑논술 ☐ 구술・발표 ☑토의・토론 ☑프로젝트 ☐ 실험・실습</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>예측</td><td>모델이 타당함</td><td>20점</td></tr>
    </table>
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "인공지능 수학").items[0]

    assert item.method == "논술 · 토의·토론 · 프로젝트"
    assert "☑" not in item.method
    assert "☐" not in item.method


def test_checked_custom_method_keeps_text_without_checkbox_marker() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 수학 개념 탐구 모델링
    <table>
      <tr><th>평가방법</th><td>þ 수학 개념 탐구 모델링</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>논리가 타당함</td><td>20점</td></tr>
    </table>
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.method == "수학 개념 탐구 모델링"


def test_bare_hwp_checkbox_control_is_not_published_as_method() -> None:
    source = """
    # 2026학년도 (경제 수학) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    가. 실생활 경제수학 탐구하기
    <table>
      <tr><th>평가방법</th><td>gfedc</td></tr>
      <tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>
      <tr><td>탐구</td><td>경제 현상을 수학적으로 설명함</td><td>20점</td></tr>
    </table>
    ### 결시자 처리 기준
    """

    item = parse_assessment_section(source, "경제 수학").items[0]

    assert item.method == ""


def test_rubric_score_column_is_not_misreported_as_the_task_total() -> None:
    source = """
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 세부 계획
    가. 로그 모델링
    <table>
      <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
      <tr><td>모델</td><td>타당함</td><td>30점</td></tr>
    </table>
    """

    item = parse_assessment_section(source, "대수").items[0]

    assert item.score == ""
    assert "30점" in item.rubric_html


def test_truncated_source_table_is_closed_for_browser_rendering() -> None:
    repaired = balance_table_tags("<table><tr><td>원문</td></tr>")

    assert repaired.count("<table") == repaired.count("</table>") == 1


def test_excessive_heading_candidates_fall_back_to_one_review_bundle() -> None:
    noisy = "\n".join(
        f"{index}. 표의 항목 {index}\n평가요소 채점기준 배점" for index in range(1, 15)
    )
    source = f"""
    # 2026학년도 (대수) 교수학습 및 평가계획
    ## 수행평가 과제별 세부 계획
    {noisy}
    """

    section = parse_assessment_section(source, "대수")

    assert len(section.items) == 1
    assert section.items[0].extraction_status == "bundle_review"


def test_detail_builder_updates_case_with_source_bounded_items(tmp_path) -> None:
    source_sha = "a" * 64
    case_id = case_identifier(source_sha, "2022", "대수")
    catalog_path = tmp_path / "catalog.jsonl"
    source_path = tmp_path / "source.jsonl"
    catalog_path.write_text(
        json.dumps(
            {
                "sha256": source_sha,
                "subject": "대수",
                "resolved_curriculum": "2022",
                "source": {"candidate_name": "평가계획.hwp"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    source_path.write_text(
        json.dumps(
            {
                "sha256": source_sha,
                "text": """
                # 2026학년도 (대수)과 교수학습 및 평가 운영 계획
                ## 수행평가 세부 기준
                1. 지수 함수 모델링
                <table>
                <tr><th>평가개요</th><td>지수 함수로 자료를 모델링한다.</td></tr>
                <tr><th>평가 방법</th><td>프로젝트</td></tr>
                <tr><th>평가요소</th><th>채점기준</th><th>점수</th></tr>
                <tr><td>모델</td><td>타당함</td><td>20점</td></tr>
                </table>
                """,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY,
            primary_task_name TEXT,
            task_names_json TEXT,
            summary_overview TEXT,
            methods_json TEXT,
            weight_summary TEXT,
            standards_json TEXT,
            criteria_json TEXT,
            title_basis TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO cases VALUES (?, '', '[]', '', '[]', '', '[]', '[]', '')",
        (case_id,),
    )
    connection.executescript(SCHEMA_SQL)

    counts = build_details(connection, catalog_path, source_path)

    assert counts["cases"] == 1
    assert counts["items"] == 1
    resumed_counts = build_details(connection, catalog_path, source_path)
    assert resumed_counts == counts
    assert (
        connection.execute(
            "SELECT primary_task_name FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()[0]
        == "지수 함수 모델링"
    )
    item = connection.execute(
        "SELECT title, source_html_zlib FROM assessment_items WHERE case_id = ?",
        (case_id,),
    ).fetchone()
    assert item[0] == "지수 함수 모델링"
    assert item[1]


def test_item_priority_requires_source_bounded_evidence() -> None:
    category, score, signals = detail_priority(
        title="지역 인구 변화 함수 모델링 탐구",
        title_basis="heading",
        extraction_status="bounded",
        overview="지역 인구 자료를 함수로 모델링한다.",
        method="프로젝트",
        weight="20%",
        score="20점",
        standards=["[12대수01-01]"],
        has_rubric=True,
    )

    assert category == "modeling"
    assert score >= 60
    assert "과제명 원문 경계 확인" in signals

    _, review_score, _ = detail_priority(
        title="대수 수행평가 원문 구간",
        title_basis="bundle",
        extraction_status="bundle_review",
        overview="",
        method="",
        weight="",
        score="",
        standards=[],
        has_rubric=False,
    )
    assert review_score == 0

    _, generic_score, generic_signals = detail_priority(
        title="발표",
        title_basis="heading",
        extraction_status="bounded",
        overview="함수의 성질을 설명한다.",
        method="발표",
        weight="20%",
        score="100점",
        standards=["[12대수01-01]"],
        has_rubric=True,
    )
    assert generic_score == 0
    assert generic_signals == []

    _, area_heading_score, area_heading_signals = detail_priority(
        title="수학주제탐구 영역",
        title_basis="heading",
        extraction_status="bounded",
        overview="수학 주제를 탐구한다.",
        method="프로젝트",
        weight="20%",
        score="100점",
        standards=["[12대수01-01]"],
        has_rubric=True,
    )
    assert area_heading_score == 0
    assert area_heading_signals == []
