from app.source_html import (
    repair_truncated_nested_rubric,
    restore_escaped_table_rows,
    rubric_tables_from_source_html,
)


def test_restores_pdf_escaped_rows_as_a_safe_html_table() -> None:
    escaped = (
        "<p>&lt;tr&gt;&lt;th colspan=&quot;2&quot;&gt;수행평가명&lt;/th&gt;"
        "&lt;td&gt;함수 모델링 탐구&lt;/td&gt;&lt;/tr&gt;</p>"
        "<p>&lt;tr&gt;&lt;th&gt;반영비율&lt;/th&gt;&lt;td&gt;20%&lt;/td&gt;"
        "&lt;td onclick=&quot;alert(1)&quot;&gt;원문 값&lt;/td&gt;&lt;/tr&gt;</p>"
        "<script>alert('unsafe')</script>"
    )

    restored = restore_escaped_table_rows(escaped)

    assert "&lt;tr" not in restored
    assert '<table><tr><th colspan="2">수행평가명</th>' in restored
    assert "함수 모델링 탐구" in restored
    assert "onclick" not in restored
    assert "<script" not in restored


def test_keeps_already_safe_source_html_unchanged() -> None:
    source = "<table><tr><th>평가명</th><td>수학 독서 글쓰기</td></tr></table>"

    assert restore_escaped_table_rows(source) == source


def test_reads_rubric_tables_from_the_restored_source_without_rewriting_cells() -> None:
    source = (
        "<table><tr><th>평가명</th><td>수학 독서 글쓰기</td></tr></table>"
        "<table><tr><th>평가요소</th><th>채점기준</th><th>배점</th></tr>"
        "<tr><td>근거</td><td>수학적 근거가 타당함</td><td>10점</td></tr></table>"
    )

    rubric = rubric_tables_from_source_html(source)

    assert "평가명" not in rubric
    assert "평가요소" in rubric
    assert "수학적 근거가 타당함" in rubric
    assert rubric.startswith("<table>")


def test_nested_rubric_keeps_cells_after_the_inner_table():
    source = (
        "<table><tr><td>평가요소 및 채점기준·배점</td><td><table><tr><td>근거를 설명함</td>"
        "<td>10점</td></tr></table></td></tr><tr><td>마지막 평가요소</td><td>20점</td></tr></table>"
    )
    result = rubric_tables_from_source_html(source)
    assert "마지막 평가요소" in result
    assert result.count("<table>") == result.count("</table>") == 2


def test_repairs_only_an_exact_truncated_nested_prefix():
    prefix = (
        "평가요소 채점기준 배점"
        + "수학적 근거를 설명하고 다른 조건에서도 적용할 수 있는지 분석한다." * 2
    )
    source = (
        f"<table><tr><td>{prefix}<table><tr><td>10점</td></tr></table></td></tr>"
        "<tr><td>마지막 기준 20점</td></tr></table>"
    )
    cut = source[: source.index("</table>") + len("</table>")] + "</table>"
    assert "마지막 기준 20점" in repair_truncated_nested_rubric(cut, source)
    separate = "<table><tr><td>채점기준: 독립된 간단한 척도</td><td>10점</td></tr></table>"
    assert repair_truncated_nested_rubric(separate, source) == separate
