"""Read-only SQLite queries for trends and evidence cases."""

from __future__ import annotations

import json
import re
import sqlite3
import zlib
from pathlib import Path
from typing import Any

from app.source_html import (
    repair_truncated_nested_rubric,
    restore_escaped_table_rows,
    rubric_tables_from_source_html,
)
from app.source_table_previews import matching_previews
from app.standard_catalog import REGISTRIES, source_standard_codes

SUBJECT_ORDER = {
    "수학": 1,
    "공통수학1": 2,
    "공통수학2": 3,
    "기본수학1": 4,
    "기본수학2": 5,
    "수학Ⅰ": 6,
    "수학Ⅱ": 7,
    "대수": 8,
    "미적분": 9,
    "미적분Ⅰ": 10,
    "미적분Ⅱ": 11,
    "확률과 통계": 12,
    "기하": 13,
    "실용 수학": 14,
    "경제 수학": 15,
    "인공지능 수학": 16,
    "직무 수학": 17,
    "수학과 문화": 18,
    "실용 통계": 19,
    "수학과제 탐구": 20,
}
CURRICULUM_ORDER = {"2015": 1, "2022": 2, "shared": 3}
SEARCH_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣ⅠⅡ]+")
ROUGH_OVERVIEW_RE = re.compile(
    r"매우\s*(?:부족|미흡)|현저히|보이지\s*않음|평가\(채점\)\s*기준|^\s*\d+\s*$"
)
UNCONFIRMED_BUNDLE_TITLE = "수행평가명 미확정 · 원문 묶음"


def parse_json_list(value: object) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def search_tokens(value: str) -> list[str]:
    return SEARCH_TOKEN_RE.findall(value)[:8]


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def case_period_filters(
    semester: str | None,
    academic_year: int | None,
) -> tuple[list[str], list[int]]:
    clauses: list[str] = []
    values: list[int] = []
    if semester == "unknown":
        clauses.append(
            "(json_array_length(c.academic_years_json) <> 1 "
            "OR json_array_length(c.semesters_json) = 0)"
        )
    elif semester is not None:
        clauses.append("EXISTS (SELECT 1 FROM json_each(c.semesters_json) WHERE value = ?)")
        values.append(int(semester))
    if academic_year is not None:
        clauses.append(
            "json_array_length(c.academic_years_json) = 1 "
            "AND json_extract(c.academic_years_json, '$[0]') = ?"
        )
        values.append(academic_year)
    return clauses, values


class CatalogRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @property
    def ready(self) -> bool:
        return self.database_path.is_file()

    def connect(self) -> sqlite3.Connection:
        if not self.ready:
            raise FileNotFoundError(self.database_path)
        connection = sqlite3.connect(
            f"file:{self.database_path.resolve()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _curated_filters(
        *,
        category: str,
        curriculum: str | None,
        subject: str | None,
        region: str | None = None,
        district: str | None = None,
    ) -> tuple[list[str], list[object]]:
        clauses = [
            "ranking.category = ?",
            "ranking.priority_score >= 38",
            "item.extraction_status = 'bounded'",
            "item.title_basis IN ('table', 'heading')",
        ]
        parameters: list[object] = [category]
        for column, value in (
            ("curriculum", curriculum),
            ("subject", subject),
            ("region", region),
            ("district", district),
        ):
            if value:
                clauses.append(f"cases.{column} = ?")
                parameters.append(value)
        return clauses, parameters

    def catalog_counts(self) -> tuple[int, int]:
        if not self.ready:
            return 0, 0
        with self.connect() as connection:
            cases = int(connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0])
            subjects = int(connection.execute("SELECT COUNT(*) FROM subject_stats").fetchone()[0])
        return cases, subjects

    def publication_counts(self) -> dict[str, object]:
        """Return public and review-only item counts from the compact catalog."""
        empty: dict[str, object] = {
            "public_cases": 0,
            "public_items": 0,
            "excluded_items": 0,
            "excluded_reasons": {},
        }
        if not self.ready:
            return empty
        with self.connect() as connection:
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
            }
            if "assessment_items" not in tables:
                return empty
            public_items = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM assessment_items
                    WHERE extraction_status = 'bounded'
                      AND title_basis IN ('table', 'heading')
                    """
                ).fetchone()[0]
            )
            public_cases = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT case_id) FROM assessment_items
                    WHERE extraction_status = 'bounded'
                      AND title_basis IN ('table', 'heading')
                    """
                ).fetchone()[0]
            )
            reason_rows = connection.execute(
                """
                SELECT extraction_status, COUNT(*) AS count
                FROM assessment_items
                WHERE NOT (
                    extraction_status = 'bounded'
                    AND title_basis IN ('table', 'heading')
                )
                GROUP BY extraction_status
                ORDER BY extraction_status
                """
            ).fetchall()
        excluded_reasons = {str(row["extraction_status"]): int(row["count"]) for row in reason_rows}
        return {
            "public_cases": public_cases,
            "public_items": public_items,
            "excluded_items": sum(excluded_reasons.values()),
            "excluded_reasons": excluded_reasons,
        }

    def subjects(self, curriculum: str | None = None) -> list[dict[str, object]]:
        sql = "SELECT * FROM subject_stats"
        parameters: tuple[object, ...] = ()
        if curriculum:
            sql += " WHERE curriculum = ?"
            parameters = (curriculum,)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        items = [self._subject_item(row) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                CURRICULUM_ORDER.get(str(item["curriculum"]), 9),
                SUBJECT_ORDER.get(str(item["subject"]), 99),
                str(item["subject"]),
            ),
        )

    def trends(
        self, curriculum: str | None = None, subject: str | None = None
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if curriculum:
            clauses.append("curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("subject = ?")
            parameters.append(subject)
        sql = "SELECT * FROM subject_stats"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            tag_rows = connection.execute(
                "SELECT * FROM subject_action_tags ORDER BY document_count DESC, tag"
            ).fetchall()
        tags: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in tag_rows:
            key = (str(row["curriculum"]), str(row["subject"]))
            tags.setdefault(key, []).append(
                {
                    "tag": str(row["tag"]),
                    "documents": int(row["document_count"]),
                    "schools": int(row["school_count"]),
                }
            )
        items = [self._trend_item(row, tags) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                CURRICULUM_ORDER.get(str(item["curriculum"]), 9),
                SUBJECT_ORDER.get(str(item["subject"]), 99),
                str(item["subject"]),
            ),
        )

    def cases(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        tag: str | None,
        region: str | None,
        district: str | None,
        source_status: str | None,
        query: str | None,
        include_ambiguous: bool,
        limit: int,
        offset: int,
        semester: str | None = None,
        academic_year: int | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        joins: list[str] = []
        clauses: list[str] = []
        parameters: list[object] = []
        search = search_tokens(query or "")
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM json_each(c.action_tags_json) WHERE value = ?)")
            parameters.append(tag)
        for token in search:
            clauses.append(
                "(c.primary_task_name LIKE ? ESCAPE '\\' "
                "OR c.task_names_json LIKE ? ESCAPE '\\' "
                "OR c.evidence_excerpt LIKE ? ESCAPE '\\' "
                "OR c.school_name LIKE ? ESCAPE '\\' "
                "OR c.subject LIKE ? ESCAPE '\\')"
            )
            pattern = like_pattern(token)
            parameters.extend([pattern, pattern, pattern, pattern, pattern])
        if curriculum:
            if include_ambiguous and subject:
                clauses.append("c.curriculum IN (?, 'shared')")
            else:
                clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        if region:
            clauses.append("c.region = ?")
            parameters.append(region)
        if district:
            clauses.append("c.district = ?")
            parameters.append(district)
        period_clauses, period_values = case_period_filters(semester, academic_year)
        clauses.extend(period_clauses)
        parameters.extend(period_values)
        if source_status == "confirmed":
            # The publication builder assigns this value only after at least one
            # bounded table/heading item passes every public-release gate.  Use
            # the materialized case marker instead of a correlated item scan on
            # every search request; the release audit verifies the invariant.
            clauses.append("c.title_basis = 'source_detail'")
        elif source_status == "review":
            clauses.append("c.title_basis = 'source_detail_bundle_review'")
        elif source_status == "unconfirmed":
            clauses.append(
                "(c.primary_task_name = '구체적 과제명 미탐지' "
                "OR c.title_basis NOT IN ('source_detail', 'source_detail_bundle_review'))"
            )
        join_sql = " ".join(joins)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(DISTINCT c.case_id) FROM cases c {join_sql}{where_sql}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT DISTINCT c.* FROM cases c {join_sql}{where_sql}
                ORDER BY c.review_score DESC, c.case_id
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        return [self._case_item(row) for row in rows], total

    def facets(
        self,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        semester: str | None = None,
        academic_year: int | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        clauses: list[str] = []
        parameters: list[object] = []
        with self.connect() as connection:
            has_detail_items = (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'assessment_items'"
                ).fetchone()
                is not None
            )
        if has_detail_items:
            # See cases(): source_detail is the audited public-case marker.
            clauses.append("c.title_basis = 'source_detail'")
        if curriculum:
            if subject:
                clauses.append("c.curriculum IN (?, 'shared')")
            else:
                clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        period_clauses, period_values = case_period_filters(semester, academic_year)
        clauses.extend(period_clauses)
        parameters.extend(period_values)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        district_clauses = [*clauses]
        district_parameters = [*parameters]
        if region:
            district_clauses.append("c.region = ?")
            district_parameters.append(region)
        district_where = " WHERE " + " AND ".join(district_clauses) if district_clauses else ""
        with self.connect() as connection:
            region_rows = connection.execute(
                f"""
                SELECT c.region AS value, COUNT(*) AS count
                FROM cases c {where_sql}
                GROUP BY c.region
                HAVING c.region != ''
                ORDER BY count DESC, value
                """,
                parameters,
            ).fetchall()
            district_rows = connection.execute(
                f"""
                SELECT c.district AS value, COUNT(*) AS count
                FROM cases c {district_where}
                GROUP BY c.district
                HAVING c.district != ''
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
            tag_rows = connection.execute(
                f"""
                SELECT cat.value AS value, COUNT(DISTINCT c.case_id) AS count
                FROM cases c
                JOIN json_each(c.action_tags_json) cat
                {district_where}
                GROUP BY cat.value
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
        return {
            "regions": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in region_rows
            ],
            "districts": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in district_rows
            ],
            "action_tags": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in tag_rows
            ],
        }

    def standard_references(
        self,
        subject: str,
        standard: str,
        semester: str | None,
        limit: int,
        offset: int,
        curriculum: str = "2022",
    ) -> dict[str, object]:
        clauses, values = case_period_filters(semester, 2026)
        where = " AND ".join(clauses)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT i.item_id, i.case_id, i.title, i.overview, i.method, i.standards_json,
                       i.rubric_html_char_count, c.school_name, c.region,
                       c.academic_years_json, c.semesters_json
                FROM assessment_items i JOIN cases c USING (case_id)
                JOIN assessment_item_rankings r ON r.item_id=i.item_id
                WHERE c.curriculum=? AND c.subject=? AND {where}
                  AND i.extraction_status='bounded' AND i.title_basis IN ('table','heading')
                ORDER BY r.priority_score DESC, i.item_id
            """,
                [curriculum, subject, *values],
            ).fetchall()
        registry = REGISTRIES[curriculum]
        subject_source = registry.get("subject_sources", {}).get(subject, registry)
        codes = [source_standard_codes(row["standards_json"], subject, curriculum) for row in rows]
        options = [
            {**entry, "count": sum(entry["key"] in found for found in codes)}
            for entry in registry["standards"]
            if entry["subject"] == subject
        ]
        selected = next((entry for entry in options if entry["key"] == standard), None)
        if not standard:
            selected = next(
                (entry for entry in options if entry["count"]), next(iter(options), None)
            )
        matches = [
            row
            for row, found in zip(rows, codes, strict=True)
            if selected and selected["key"] in found
        ]
        return {
            "curriculum": curriculum,
            "subject": subject,
            "standard": selected,
            "standards": options,
            "total": len(matches),
            "source_url": subject_source["source_url"],
            "items": [
                {
                    "item_id": row["item_id"],
                    "case_id": row["case_id"],
                    "title": row["title"],
                    "overview": row["overview"],
                    "method": row["method"],
                    "school_name": row["school_name"],
                    "region": row["region"],
                    "academic_years": parse_json_list(row["academic_years_json"]),
                    "semesters": parse_json_list(row["semesters_json"]),
                    "has_rubric": bool(row["rubric_html_char_count"]),
                    "standards": parse_json_list(row["standards_json"]),
                }
                for row in matches[offset : offset + limit]
            ],
        }

    def design_references(
        self,
        topic: str,
        method: str,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        with self.connect() as db:
            ready = db.execute(
                "SELECT 1 FROM sqlite_schema WHERE name='design_index_tags'"
            ).fetchone()
            if not ready:
                return {
                    "available": False,
                    "indexed_items": 0,
                    "total": 0,
                    "topics": {},
                    "methods": {},
                    "items": [],
                }
            joins = """
                FROM design_index_items pilot
                JOIN assessment_items item ON item.item_id=pilot.item_id
                JOIN cases c ON c.case_id=item.case_id
                JOIN assessment_item_rankings ranking ON ranking.item_id=item.item_id
            """
            public = "item.extraction_status='bounded' AND item.title_basis IN ('table','heading')"
            filter_axis = """EXISTS (SELECT 1 FROM design_index_tags tag
                WHERE tag.item_id=pilot.item_id AND tag.axis=? AND tag.tag=?)"""
            filters = [pair for pair in (("topic", topic), ("method", method)) if pair[1]]
            where = " AND ".join([public, *([filter_axis] * len(filters))])
            values = [value for pair in filters for value in pair]
            items = db.execute(
                f"""
                SELECT item.item_id, item.case_id, item.title, item.rubric_html_char_count,
                       c.school_name, c.region
                {joins} WHERE {where}
                ORDER BY ranking.priority_score DESC, item.item_id LIMIT ? OFFSET ?
            """,
                [*values, limit, offset],
            ).fetchall()
            total = db.execute(f"SELECT count(*) {joins} WHERE {where}", values).fetchone()[0]
            indexed_items = db.execute(f"SELECT count(*) {joins} WHERE {public}").fetchone()[0]
            facets = {}
            for axis, opposite, value in (("topic", "method", method), ("method", "topic", topic)):
                conditions = [public, "facet.axis=?"]
                parameters = [axis]
                if value:
                    conditions.append(filter_axis)
                    parameters.extend((opposite, value))
                facets[axis] = dict(
                    db.execute(
                        f"""
                    SELECT facet.tag, count(*) {joins}
                    JOIN design_index_tags facet ON facet.item_id=pilot.item_id
                    WHERE {" AND ".join(conditions)} GROUP BY facet.tag
                """,
                        parameters,
                    ).fetchall()
                )
            result = []
            for item in items:
                tags = db.execute(
                    """SELECT axis, tag, source_field, evidence FROM design_index_tags
                    WHERE item_id=? ORDER BY axis, tag""",
                    (item["item_id"],),
                ).fetchall()
                result.append(
                    {
                        "item_id": item["item_id"],
                        "case_id": item["case_id"],
                        "title": item["title"],
                        "school_name": item["school_name"],
                        "region": item["region"],
                        "has_rubric": bool(item["rubric_html_char_count"]),
                        "tags": [dict(tag) for tag in tags],
                    }
                )
            return {
                "available": True,
                "indexed_items": indexed_items,
                "total": total,
                "topics": facets["topic"],
                "methods": facets["method"],
                "items": result,
            }

    def case(self, case_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return self._case_item(row) if row else None

    def case_detail(self, case_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            status = connection.execute(
                "SELECT * FROM case_detail_status WHERE case_id = ?", (case_id,)
            ).fetchone()
            if status is None:
                return None
            rows = connection.execute(
                """
                SELECT item_id, item_order, title, title_raw, title_basis,
                       extraction_status, overview, method, timing, score,
                       weight, standards_json, rubric_html_char_count
                FROM assessment_items
                WHERE case_id = ?
                  AND extraction_status = 'bounded'
                  AND title_basis IN ('table', 'heading')
                ORDER BY item_order
                """,
                (case_id,),
            ).fetchall()
        if not rows:
            return None
        confirmed_titles = [str(row["title"]) for row in rows]
        return {
            "case_id": case_id,
            "source_format": str(status["source_format"]),
            "boundary_status": str(status["boundary_status"]),
            "extraction_status": "bounded",
            "detected_titles": confirmed_titles,
            "source_section_char_count": int(status["source_section_char_count"]),
            "items": [self._assessment_item_summary(row) for row in rows],
        }

    def assessment_item(self, item_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            case_columns = {
                str(column[1]) for column in connection.execute("PRAGMA table_info(cases)")
            }
            district_select = "cases.district" if "district" in case_columns else "'' AS district"
            row = connection.execute(
                f"""
                SELECT item.*, cases.curriculum, cases.subject, cases.school_name,
                       cases.region, {district_select}, cases.candidate_name,
                       cases.source_url, cases.source_sha256
                FROM assessment_items item
                JOIN cases ON cases.case_id = item.case_id
                WHERE item.item_id = ?
                """,
                (item_id,),
            ).fetchone()
        if row is None:
            return None
        if str(row["extraction_status"]) != "bounded" or str(row["title_basis"]) not in {
            "table",
            "heading",
        }:
            return None
        item = self._assessment_item_summary(row)
        # Public HTML is limited to individually bounded assessment sections.
        # Bundled/review and cross-subject matches retain metadata only until a
        # teacher-safe boundary and privacy review is completed.
        source_available = str(row["extraction_status"]) == "bounded"
        source_html = ""
        rubric_html = ""
        if source_available:
            source_html = restore_escaped_table_rows(
                zlib.decompress(row["source_html_zlib"]).decode("utf-8")
            )
            rubric_html = restore_escaped_table_rows(
                zlib.decompress(row["rubric_html_zlib"]).decode("utf-8")
            )
            if not rubric_html.strip():
                rubric_html = rubric_tables_from_source_html(source_html)
            else:
                rubric_html = repair_truncated_nested_rubric(rubric_html, source_html)
            item["has_rubric"] = bool(rubric_html.strip())
        item.update(
            {
                "case_id": str(row["case_id"]),
                "curriculum": str(row["curriculum"]),
                "subject": str(row["subject"]),
                "school_name": str(row["school_name"]),
                "region": str(row["region"]),
                "district": str(row["district"]),
                "source_name": str(row["candidate_name"]),
                "source_url": str(row["source_url"]),
                "source_html": source_html,
                "rubric_html": rubric_html,
                **matching_previews(
                    str(row["item_id"]),
                    str(row["source_sha256"]),
                    bytes(row["source_html_zlib"]) if source_available else None,
                    bytes(row["rubric_html_zlib"]) if source_available else None,
                ),
            }
        )
        return item

    def curated_items(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
        limit: int,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            has_rankings = (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                    "AND name = 'assessment_item_rankings'"
                ).fetchone()
                is not None
            )
            if has_rankings:
                case_columns = {
                    str(column[1]) for column in connection.execute("PRAGMA table_info(cases)")
                }
                has_district = "district" in case_columns
                if district and not has_district:
                    return []
                clauses, parameters = self._curated_filters(
                    category=category,
                    curriculum=curriculum,
                    subject=subject,
                    region=region,
                    district=district,
                )
                district_select = "cases.district" if has_district else "'' AS district"
                rows = connection.execute(
                    f"""
                    SELECT item.*, ranking.category, ranking.priority_score,
                           ranking.priority_signals_json, cases.curriculum,
                           cases.subject, cases.school_name, cases.region, {district_select}
                    FROM assessment_items item
                    JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
                    JOIN cases ON cases.case_id = item.case_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY ranking.priority_score DESC, item.item_id
                    LIMIT ?
                    """,
                    [*parameters, limit],
                ).fetchall()
            else:
                rows = []
        if has_rankings:
            output: list[dict[str, object]] = []
            for row in rows:
                item = self._assessment_item_summary(row)
                item.update(
                    {
                        "case_id": str(row["case_id"]),
                        "curriculum": str(row["curriculum"]),
                        "subject": str(row["subject"]),
                        "school_name": str(row["school_name"]),
                        "region": str(row["region"]),
                        "district": str(row["district"]),
                        "category": str(row["category"]),
                        "priority_score": int(row["priority_score"]),
                        "priority_signals": [
                            str(value) for value in parse_json_list(row["priority_signals_json"])
                        ],
                    }
                )
                output.append(item)
            return output

        legacy = self.curated_cases(
            curriculum=curriculum,
            subject=subject,
            region=region,
            district=district,
            category=category,
            limit=limit,
        )
        return [
            {
                "item_id": f"legacy-{item['case_id']}",
                "order": 1,
                "title": str(item["primary_task_name"]),
                "title_raw": str(item["primary_task_name"]),
                "title_basis": str(item["assessment_structure"]["basis"]),
                "extraction_status": "legacy",
                "overview": str(item["assessment_structure"]["overview"]),
                "method": " · ".join(item["assessment_structure"]["methods"]),
                "timing": "",
                "score": "",
                "weight": str(item["assessment_structure"]["weight"]),
                "standards": list(item["assessment_structure"]["standards"]),
                "has_rubric": bool(item["evidence_markers"]["rubric"]),
                "case_id": str(item["case_id"]),
                "curriculum": str(item["curriculum"]),
                "subject": str(item["subject"]),
                "school_name": str(item["school_name"]),
                "region": str(item["region"]),
                "district": str(item["district"]),
                "category": str(item["category"]),
                "priority_score": int(item["priority_score"]),
                "priority_signals": list(item["priority_signals"]),
            }
            for item in legacy
        ]

    def curated_total(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
    ) -> int:
        clauses, parameters = self._curated_filters(
            category=category,
            curriculum=curriculum,
            subject=subject,
            region=region,
            district=district,
        )
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM assessment_items item
                JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
                JOIN cases ON cases.case_id = item.case_id
                WHERE {" AND ".join(clauses)}
                """,
                parameters,
            ).fetchone()
        return int(row[0])

    def curated_facets(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        category: str,
    ) -> dict[str, list[dict[str, object]]]:
        clauses, parameters = self._curated_filters(
            category=category,
            curriculum=curriculum,
            subject=subject,
        )
        where_sql = " AND ".join(clauses)
        district_clauses = [*clauses]
        district_parameters = [*parameters]
        if region:
            district_clauses.append("cases.region = ?")
            district_parameters.append(region)
        joins = """
            FROM assessment_items item
            JOIN assessment_item_rankings ranking ON ranking.item_id = item.item_id
            JOIN cases ON cases.case_id = item.case_id
        """
        with self.connect() as connection:
            region_rows = connection.execute(
                f"""
                SELECT cases.region AS value, COUNT(*) AS count
                {joins}
                WHERE {where_sql} AND cases.region != ''
                GROUP BY cases.region
                ORDER BY count DESC, value
                """,
                parameters,
            ).fetchall()
            district_rows = connection.execute(
                f"""
                SELECT cases.district AS value, COUNT(*) AS count
                {joins}
                WHERE {" AND ".join(district_clauses)} AND cases.district != ''
                GROUP BY cases.district
                ORDER BY count DESC, value
                """,
                district_parameters,
            ).fetchall()
        return {
            "regions": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in region_rows
            ],
            "districts": [
                {"value": str(row["value"]), "count": int(row["count"])} for row in district_rows
            ],
            "action_tags": [],
        }

    def curated_cases(
        self,
        *,
        curriculum: str | None,
        subject: str | None,
        region: str | None,
        district: str | None,
        category: str,
        limit: int,
    ) -> list[dict[str, object]]:
        with self.connect() as connection:
            has_detail_items = (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'assessment_items'"
                ).fetchone()
                is not None
            )
        clauses = [
            "c.category = ?",
            "c.priority_score >= 38",
            "c.primary_task_name NOT LIKE '%' || char(10) || '%'",
            "c.primary_task_name NOT LIKE '%문맥 전환%'",
            "c.primary_task_name NOT LIKE '평가 방법:%'",
            "c.primary_task_name NOT GLOB '* [0-9]'",
            "NOT (c.subject NOT LIKE '미적분%' AND c.primary_task_name LIKE '%미적분%')",
        ]
        if has_detail_items:
            clauses.extend(
                [
                    "c.title_basis = 'source_detail'",
                    "EXISTS (SELECT 1 FROM assessment_items detail_item "
                    "WHERE detail_item.case_id = c.case_id "
                    "AND detail_item.extraction_status = 'bounded' "
                    "AND detail_item.title_basis IN ('table', 'heading'))",
                ]
            )
        else:
            clauses.append("c.title_basis IN ('table', 'heading')")
        parameters: list[object] = [category]
        if curriculum:
            clauses.append("c.curriculum = ?")
            parameters.append(curriculum)
        if subject:
            clauses.append("c.subject = ?")
            parameters.append(subject)
        if region:
            clauses.append("c.region = ?")
            parameters.append(region)
        if district:
            clauses.append("c.district = ?")
            parameters.append(district)
        where_sql = " AND ".join(clauses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.* FROM cases c
                WHERE {where_sql}
                ORDER BY c.priority_score DESC, c.review_score DESC, c.case_id
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
        return [self._case_item(row) for row in rows]

    @staticmethod
    def _subject_item(row: sqlite3.Row) -> dict[str, object]:
        curriculum = str(row["curriculum"])
        return {
            "curriculum": curriculum,
            "subject": str(row["subject"]),
            "documents": int(row["documents"]),
            "schools": int(row["schools"]),
            "small_sample": bool(row["small_sample"]),
            "curriculum_ambiguous": curriculum == "shared",
        }

    @classmethod
    def _trend_item(
        cls,
        row: sqlite3.Row,
        tags: dict[tuple[str, str], list[dict[str, object]]],
    ) -> dict[str, object]:
        item = cls._subject_item(row)
        key = (str(row["curriculum"]), str(row["subject"]))
        item.update(
            {
                "academic_years": [
                    int(value) for value in parse_json_list(row["academic_years_json"])
                ],
                "grade_documents": {
                    "1": int(row["grade1_documents"]),
                    "2": int(row["grade2_documents"]),
                    "3": int(row["grade3_documents"]),
                },
                "evidence_documents": {
                    "rubric": int(row["rubric_documents"]),
                    "achievement_standard": int(row["achievement_standard_documents"]),
                    "weight_or_points": int(row["weight_or_points_documents"]),
                    "assessment_method": int(row["assessment_method_documents"]),
                },
                "median_evidence_score": row["median_review_score"],
                "task_name_candidates": int(row["task_name_candidates"]),
                "action_tags": tags.get(key, []),
                "coverage": {
                    "found": row["coverage_found"],
                    "found_curriculum_ambiguous": row["coverage_ambiguous"],
                    "not_found_in_collected_plans": row["coverage_not_found"],
                    "offering_unknown": row["coverage_offering_unknown"],
                    "extraction_failed": row["coverage_extraction_failed"],
                },
            }
        )
        return item

    @staticmethod
    def _case_item(row: sqlite3.Row) -> dict[str, object]:
        curriculum = str(row["curriculum"])
        overview = re.sub(r"\s+", " ", str(row["summary_overview"])).strip()
        if ROUGH_OVERVIEW_RE.search(overview):
            overview = ""
        title_basis = str(row["title_basis"])
        primary_task_name = str(row["primary_task_name"])
        task_names = [str(value) for value in parse_json_list(row["task_names_json"])]

        # A bundle without a source-table title is useful for coverage, but its
        # legacy catalogue title can be a rubric heading or a neighbouring
        # subject's text.  Never present that value as a confirmed task name.
        # The original is retained only in the private/audit database, while
        # teachers see the honest boundary state and can follow the official
        # Schoolinfo link for the full document.
        if title_basis == "source_detail_bundle_review":
            primary_task_name = UNCONFIRMED_BUNDLE_TITLE
            task_names = []
        return {
            "case_id": str(row["case_id"]),
            "curriculum": curriculum,
            "subject": str(row["subject"]),
            "curriculum_ambiguous": curriculum == "shared",
            "curriculum_basis": str(row["curriculum_basis"]),
            "school_name": str(row["school_name"]),
            "region": str(row["region"]),
            "district": str(row["district"]) if "district" in row.keys() else "",
            "academic_years": [int(value) for value in parse_json_list(row["academic_years_json"])],
            "grades": [int(value) for value in parse_json_list(row["grades_json"])],
            "semesters": [int(value) for value in parse_json_list(row["semesters_json"])],
            "primary_task_name": primary_task_name,
            "task_names": task_names,
            "action_tags": [str(value) for value in parse_json_list(row["action_tags_json"])],
            "evidence_markers": {
                "rubric": int(row["rubric_marker_count"]),
                "achievement_standard": int(row["achievement_standard_marker_count"]),
                "weight_or_points": int(row["weight_or_points_marker_count"]),
                "assessment_method": int(row["assessment_method_marker_count"]),
            },
            "evidence_score": int(row["review_score"]),
            "evidence_excerpt": str(row["evidence_excerpt"]),
            "assessment_structure": {
                "overview": overview,
                "methods": [str(value) for value in parse_json_list(row["methods_json"])],
                "weight": (
                    ""
                    if str(row["weight_summary"]) in {"0점", "0%"}
                    else str(row["weight_summary"])
                ),
                "standards": [str(value) for value in parse_json_list(row["standards_json"])],
                "criteria": [str(value) for value in parse_json_list(row["criteria_json"])],
                "basis": title_basis,
            },
            "category": str(row["category"]),
            "priority_score": int(row["priority_score"]),
            "priority_signals": [
                str(value) for value in parse_json_list(row["priority_signals_json"])
            ],
            "source_name": str(row["candidate_name"]),
            "source_url": str(row["source_url"]),
            "source_sha256": str(row["source_sha256"]),
        }

    @staticmethod
    def _assessment_item_summary(row: sqlite3.Row) -> dict[str, object]:
        source_available = str(row["extraction_status"]) == "bounded"
        return {
            "item_id": str(row["item_id"]),
            "order": int(row["item_order"]),
            "title": str(row["title"]),
            "title_raw": str(row["title_raw"]),
            "title_basis": str(row["title_basis"]),
            "extraction_status": str(row["extraction_status"]),
            "overview": str(row["overview"]),
            "method": str(row["method"]),
            "timing": str(row["timing"]),
            "score": str(row["score"]),
            "weight": str(row["weight"]),
            "standards": [str(value) for value in parse_json_list(row["standards_json"])],
            "has_rubric": source_available and int(row["rubric_html_char_count"]) > 0,
            "source_available": source_available,
        }
