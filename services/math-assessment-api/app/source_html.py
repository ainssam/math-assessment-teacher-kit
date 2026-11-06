"""Safe presentation repairs for source HTML preserved in the catalogue."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

ESCAPED_ROW_PARAGRAPH_RE = re.compile(
    r"<p>\s*(&lt;tr\b.*?&lt;/tr&gt;)\s*</p>",
    flags=re.IGNORECASE | re.DOTALL,
)
ESCAPED_TABLE_WRAPPER_RE = re.compile(
    r"<p>\s*&lt;/?table(?:\s+.*?)?&gt;\s*</p>",
    flags=re.IGNORECASE | re.DOTALL,
)
UNSAFE_BLOCK_RE = re.compile(
    r"<(script|style|iframe|object)\b.*?</\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
TABLE_RE = re.compile(r"<table\b.*?</table\s*>", flags=re.IGNORECASE | re.DOTALL)


class _SafeTableParser(HTMLParser):
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


def _safe_table(value: str) -> str:
    parser = _SafeTableParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def restore_escaped_table_rows(value: str) -> str:
    """Turn escaped PDF/HWP table rows into real, safe HTML tables.

    Some converters emitted each ``<tr>`` as escaped text inside a paragraph.
    Consecutive row paragraphs are one source table; the function only restores
    that lost structure and does not rewrite any cell text.
    """

    matches = list(ESCAPED_ROW_PARAGRAPH_RE.finditer(value))
    if not matches:
        return value

    source = ESCAPED_TABLE_WRAPPER_RE.sub("", value)
    matches = list(ESCAPED_ROW_PARAGRAPH_RE.finditer(source))
    output: list[str] = []
    pending_rows: list[str] = []
    cursor = 0

    def flush_rows() -> None:
        if not pending_rows:
            return
        output.append(_safe_table(f"<table>{''.join(pending_rows)}</table>"))
        pending_rows.clear()

    for match in matches:
        between = source[cursor : match.start()]
        if pending_rows and between.strip():
            flush_rows()
            output.append(between)
        elif not pending_rows:
            output.append(between)
        pending_rows.append(html.unescape(match.group(1)))
        cursor = match.end()

    tail = source[cursor:]
    flush_rows()
    output.append(tail)
    return UNSAFE_BLOCK_RE.sub("", "".join(output))


def rubric_tables_from_source_html(value: str) -> str:
    """Return only source tables that visibly contain criteria and scoring fields."""

    rubric_tables: list[str] = []
    for match in TABLE_RE.finditer(value):
        table = match.group(0)
        visible = re.sub(r"<[^>]+>", " ", html.unescape(table))
        visible = re.sub(r"\s+", " ", visible)
        has_criteria = re.search(
            r"채점\s*기준|평가\s*요소|세부\s*(?:평가\s*)?기준|평가\s*척도",
            visible,
        )
        has_scale = re.search(r"배점|점수|척도|성취\s*수준", visible)
        if has_criteria and has_scale:
            rubric_tables.append(_safe_table(table))
    return "\n".join(rubric_tables)
