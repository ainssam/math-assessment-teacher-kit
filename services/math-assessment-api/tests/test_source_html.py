from app.source_html import restore_escaped_table_rows, rubric_tables_from_source_html


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
