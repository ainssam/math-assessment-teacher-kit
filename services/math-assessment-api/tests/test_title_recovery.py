from scripts.audit_unresolved_math_assessment_titles import (
    TITLE_FRAGMENT_RE,
    candidate_rows,
    explicit_name_label,
    split_concatenated_titles,
    standard_alignment,
)
from scripts.promote_recovered_math_assessment_titles import candidates_by_case
from scripts.propose_math_assessment_explicit_item_recovery import (
    source_course_identity_evidence,
)


def test_assessment_task_field_is_an_explicit_title_field() -> None:
    """2022 plan tables use 평가 과제 for the original task name."""

    assert explicit_name_label("평가 과제")
    assert explicit_name_label("평가과제")
    # A long 수행 과제 cell frequently describes directions, not the title.
    assert not explicit_name_label("수행 과제")
    assert TITLE_FRAGMENT_RE.fullmatch("・포트폴리오")


def test_task_name_is_not_split_before_a_connective_continuation() -> None:
    title = "실생활 문제 만들기 및 풀이하기"
    assert split_concatenated_titles(title) == [title]


def test_adjacent_complete_task_names_can_still_be_split() -> None:
    assert split_concatenated_titles("함수 탐구하기 수열 분석하기") == [
        "함수 탐구하기",
        "수열 분석하기",
    ]


def test_performance_task_cell_preserves_the_complete_source_value() -> None:
    value = "함수 탐구하기 보고서 작성하기 발표하기"
    assert candidate_rows(f"수행 과제\t{value}") == [
        ("수행 과제", value, "table_row", 0)
    ]


def test_recovery_alignment_accepts_grade_course_separator_variant() -> None:
    assert standard_alignment("[12-대수01-05]", "대수") == "expected"
    assert standard_alignment("[12-대수01-05]", "기하") == "other"


def test_source_title_can_prove_a_specific_course_without_codes() -> None:
    assert source_course_identity_evidence(
        alignment="unknown",
        title="진로에 맞는 미적분 주제를 선정하여 탐구하기",
        subject="미적분",
    )
    assert not source_course_identity_evidence(
        alignment="unknown",
        title="수학적 사실을 바탕으로 탐구하기",
        subject="공통수학1",
    )
    assert not source_course_identity_evidence(
        alignment="other",
        title="대수의 눈으로 다시 읽기",
        subject="대수",
    )


def test_title_recovery_promotes_only_direct_source_verified_titles() -> None:
    audit = {
        "candidates": [
            {
                "case_id": "case-1",
                "candidate": "실생활 함수 모델링 보고서",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-1",
                "candidate": "실생활 함수 모델링 보고서",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-2",
                "candidate": "문학 비평문 작성",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": True,
            },
            {
                "case_id": "case-3",
                "candidate": "수행평가 원문 구간",
                "confidence": "high",
                "detection": "table_row",
                "subject_alignment": "expected",
                "explicit_name_label": True,
                "title_looks_complete": True,
                "other_subject_signal": False,
            },
            {
                "case_id": "case-4",
                "candidate": "표가 무너진 후보",
                "confidence": "review",
                "detection": "flattened_line",
                "subject_alignment": "unknown",
                "explicit_name_label": False,
                "title_looks_complete": False,
                "other_subject_signal": False,
            },
        ]
    }

    selected, skipped = candidates_by_case(audit)

    assert selected == {"case-1": ["실생활 함수 모델링 보고서"]}
    assert skipped == {
        "missing_case_or_title": 1,
        "not_source_verified_high": 1,
        "other_subject_signal": 1,
    }
