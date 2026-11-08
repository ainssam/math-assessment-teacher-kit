"""가상 학교만 쓰는 공개 연구 CLI 계약/범위 검사. 네트워크 호출 없음."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "math_assessment_research", ROOT / "scripts/math_assessment_research.py"
)
research = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)

CASE = "a" * 24
ITEMS = [f"{number:028x}" for number in range(1, 9)]
META = {"catalog_ready": True, "public_cases": 123, "public_items": 456}
CASE_ROW = {
    "case_id": CASE,
    "school_name": "가상고등학교",
    "region": "가상도",
    "district": "가상시",
    "subject": "기하",
    "curriculum": "2022",
    "academic_years": [2026],
    "semesters": [2],
    "source_url": "https://example.org/official-fictional-plan",
    "task_names": ["가상 도형 탐구"],
    "primary_task_name": "가상 도형 탐구",
}


def item_row(item_id):
    return {
        "item_id": item_id,
        "case_id": CASE,
        "title": "가상 도형 탐구",
        "subject": "기하",
        "curriculum": "2022",
        "school_name": "가상고등학교",
        "region": "가상도",
        "source_url": CASE_ROW["source_url"],
        "has_rubric": True,
        "source_available": True,
        "source_html": "<p>가상 도형 탐구</p>"
        "<table><tr><td>개요</td><td>도형의 식 세우기</td></tr></table>",
        "rubric_html": "<table><tr><td>조건 해석</td><td>4점</td></tr></table>",
        "source_notes": ["가상 검토 메모"],
        "source_previews": [
            {"url": "/source-previews/fake.webp", "page": 3, "width": 100, "height": 200}
        ],
        "rubric_previews": [{"url": "javascript:alert(1)", "page": 3, "width": 100, "height": 200}],
        "source_excerpt_covered": True,
    }


class Response(io.BytesIO):
    pass


class ResearchClientTests(unittest.TestCase):
    def transport(self, routes):
        calls = []

        def open_request(request, timeout):
            calls.append(request)
            path = urlsplit(request.full_url).path.removeprefix("/api/v1/")
            payload = routes[path]
            if isinstance(payload, Exception):
                raise payload
            return Response(json.dumps(payload, ensure_ascii=False).encode())

        return calls, patch.object(research, "urlopen", side_effect=open_request)

    def test_get_allowlist_parameters_cache_and_no_credentials(self):
        calls, transport = self.transport({"cases": {"items": [], "total": 0}})
        with transport:
            client = research.ApiClient()
            client.get(
                "cases", subject="기하", semester="2", academic_year=2026, include_ambiguous=False
            )
            client.get(
                "cases", subject="기하", semester="2", academic_year=2026, include_ambiguous=False
            )
            with self.assertRaises(research.ResearchError):
                client.get("visitors")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_method(), "GET")
        self.assertIsNone(calls[0].get_header("Authorization"))
        self.assertIsNone(calls[0].data)
        self.assertEqual(
            parse_qs(urlsplit(calls[0].full_url).query)["include_ambiguous"], ["false"]
        )

    def test_safe_text_keeps_cell_boundaries_and_flags_pua(self):
        text = research.plain_text(
            "<script>steal()</script><style>.secret{}</style><p>A&amp;B</p><table><tr><td>근거</td><td>4점</td></tr></table><p></p>"
        )
        self.assertEqual(text, "A&B\n근거\t4점\n")
        self.assertTrue(research.private_use(text))
        self.assertNotIn("steal", text)

    def test_item_preserves_period_source_notes_and_separates_rubric(self):
        row = item_row(ITEMS[0])
        row["source_html"] += "<p></p>"
        calls, transport = self.transport(
            {"assessment-items/" + ITEMS[0]: row, "cases/" + CASE: CASE_ROW}
        )
        with transport:
            result = research.assessment(research.ApiClient(), ITEMS[0])
        self.assertEqual(result["academic_years"], [2026])
        self.assertEqual(result["semesters"], [2])
        self.assertEqual(result["source_notes"][0], "가상 검토 메모")
        self.assertIn("조건 해석\t4점", result["rubric"]["text"])
        self.assertNotIn("html", result["source"])
        self.assertTrue(result["needs_image_review"])
        self.assertEqual(
            result["source"]["previews"][0]["url"],
            "https://suhaeng-math.vercel.app/source-previews/fake.webp",
        )
        self.assertEqual(result["rubric"]["previews"], [])
        self.assertEqual(len(calls), 2)

    def test_bundle_caps_items_not_just_cases_and_exposes_scope(self):
        routes = {
            "cases": {"items": [CASE_ROW], "total": 1},
            "cases/" + CASE + "/detail": {"items": [{"item_id": item_id} for item_id in ITEMS]},
        }
        routes.update({"assessment-items/" + item_id: item_row(item_id) for item_id in ITEMS})
        calls, transport = self.transport(routes)
        with transport:
            result = research.bundle(
                research.ApiClient(), {"subject": "기하", "academic_year": 2026, "semester": "2"}
            )
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(result["scope"]["matched_total"], 1)
        self.assertEqual(result["scope"]["matched_total_unit"], "cases")
        self.assertEqual(result["scope"]["retrieved_items_count"], 5)
        self.assertEqual(result["scope"]["omitted_candidate_items_on_this_page"], 3)
        self.assertTrue(result["scope"]["truncated"])
        self.assertFalse(result["scope"]["case_page_truncated"])
        self.assertTrue(result["scope"]["items_truncated_by_cap"])
        self.assertFalse(result["scope"]["is_national_census"])
        self.assertEqual(len(calls), 7)
        query = parse_qs(urlsplit(calls[0].full_url).query)
        self.assertEqual(query["academic_year"], ["2026"])
        self.assertEqual(query["semester"], ["2"])

    def test_empty_reference_does_not_fall_back_to_unrelated_cases(self):
        calls, transport = self.transport({"references": {"items": [], "total": 0}})
        with transport:
            result = research.references(
                research.ApiClient(), {"subject": "기하"}, "inquiry", 5, False
            )
        self.assertEqual(result["items"], [])
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["scope"]["period_filter_supported"])

    def test_standard_code_and_fixed_2026_scope(self):
        payload = {
            "items": [],
            "total": 0,
            "standard": {"key": "12기하01-01", "code": "[12기하01-01]"},
            "standards": [],
            "subject": "기하",
            "curriculum": "2022",
            "source_url": "https://example.org/curriculum",
        }
        calls, transport = self.transport({"standard-references": payload})
        with transport:
            result = research.standards(
                research.ApiClient(), subject="기하", standard="[12기하01-01]", offset=5
            )
            with self.assertRaises(research.ResearchError):
                research.standards(research.ApiClient(), subject="기하", standard="12기하99-99")
        self.assertEqual(result["scope"]["academic_year"], 2026)
        self.assertEqual(result["scope"]["offset_unit"], "assessment_items")
        self.assertTrue(result["scope"]["truncated"])
        self.assertEqual(parse_qs(urlsplit(calls[0].full_url).query)["standard"], ["12기하01-01"])

    def test_partial_bundle_is_explicit_and_never_invents_missing_item(self):
        routes = {
            "assessment-items/" + ITEMS[0]: item_row(ITEMS[0]),
            "cases/" + CASE: CASE_ROW,
            "assessment-items/" + ITEMS[1]: HTTPError(
                "https://example.org", 404, "not found", {}, None
            ),
        }
        _, transport = self.transport(routes)
        with transport:
            result = research.bundle(
                research.ApiClient(), {}, item_ids=ITEMS[:2], include_html=True
            )
        self.assertEqual(result["scope"]["matched_total"], 2)
        self.assertEqual(result["scope"]["returned_count"], 1)
        self.assertEqual(result["scope"]["fetch_error_count"], 1)
        self.assertFalse(result["scope"]["retrieval_complete"])
        self.assertIn("html", result["items"][0]["source"])
        self.assertIn("404", result["fetch_errors"][0]["error"])

    def test_cli_refuses_overwrite_before_any_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "kept.json"
            output.write_text("original", "utf-8")
            with (
                patch.object(research, "urlopen") as network,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = research.main(["meta", "--output", str(output)])
            self.assertEqual(code, 2)
            network.assert_not_called()
            self.assertEqual(output.read_text("utf-8"), "original")

    def test_cli_writes_new_utf8_output_with_only_mock_data(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs" / "가상예제.json"
            calls, transport = self.transport({"meta": META})
            with transport, contextlib.redirect_stderr(io.StringIO()):
                code = research.main(["meta", "--output", str(output)])
            self.assertEqual(code, 0)
            result = json.loads(output.read_text("utf-8"))
            self.assertEqual(result["catalog_snapshot"], META)
            self.assertFalse(result["scope"]["is_national_census"])
            self.assertEqual(len(calls), 1)

    def test_search_offset_and_unknown_period_are_not_silently_dropped(self):
        calls, transport = self.transport({"meta": META, "cases": {"items": [], "total": 9}})
        with transport:
            args = research.parser().parse_args(
                [
                    "search",
                    "--subject",
                    "기하",
                    "--semester",
                    "unknown",
                    "--limit",
                    "2",
                    "--offset",
                    "4",
                ]
            )
            result = research.execute(args)
        query = parse_qs(urlsplit(calls[1].full_url).query)
        self.assertEqual(query["semester"], ["unknown"])
        self.assertEqual(query["offset"], ["4"])
        self.assertEqual(result["scope"]["returned_count"], 0)
        self.assertEqual(result["scope"]["matched_total"], 9)

    def test_bad_contract_and_not_ready_are_errors_not_empty_results(self):
        with self.assertRaises(research.ResearchError):
            research.result_list({"items": [], "total": "unknown"})
        with self.assertRaises(research.ResearchError):
            research.result_list({"items": [{}, {}], "total": 2}, limit=1)
        with self.assertRaises(research.ResearchError):
            research.result_list({"items": [{}], "total": 0})
        _, transport = self.transport({"meta": {"catalog_ready": False}})
        with transport, self.assertRaises(research.ResearchError):
            research.execute(research.parser().parse_args(["meta"]))


if __name__ == "__main__":
    unittest.main()
