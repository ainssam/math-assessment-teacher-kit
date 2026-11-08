"""공식 SDK in-memory/HTTP와 가상 SQLite만 사용하는 MCP 계약 검사."""

import asyncio
import base64
import hashlib
import io
import json
import sqlite3
import zlib
from http.client import IncompleteRead
from urllib.error import HTTPError

import pytest
from mcp import Client
from scripts.build_math_assessment_detail_db import SCHEMA_SQL as DETAIL_SCHEMA
from scripts.build_math_assessment_publish_db import SCHEMA_SQL as CATALOG_SCHEMA
from scripts.package_math_assessment_vercel_data import package_catalog
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app import research_tools, source_table_previews
from app.mcp_server import INSTRUCTIONS, MCPHttpRuntime, create_mcp_server, transport_settings
from app.repository import CatalogRepository
from app.research_tools import MAX_IMAGE_BYTES, ResearchTools, ToolDataError, public_base

CASE = "a" * 24
ITEMS = [f"{number:028x}" for number in range(1, 13)]
HELD = "f" * 28
PIXELS = base64.b64decode("UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA=")
ASSET = "1" * 64 + ".webp"


def insert_row(connection, table, values):
    defaults = {}
    for column in connection.execute(f"PRAGMA table_info({table})"):
        name, kind = column[1], column[2]
        defaults[name] = (
            "[]" if name.endswith("_json") else 0 if kind in {"INTEGER", "REAL"} else ""
        )
    defaults.update(values)
    names = ",".join(defaults)
    marks = ",".join("?" for _ in defaults)
    connection.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(defaults.values()))


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    database = tmp_path / "fictional.sqlite"
    source = "<h2>가상 포물선 탐구</h2><p></p>" + "<p>가상 추론 근거</p>" * 500
    rubric = (
        "<table><tr><td>조건 해석</td><td>4점</td></tr><tr><td>설명</td><td>6점</td></tr></table>"
    )
    source_blob, rubric_blob = (zlib.compress(value.encode()) for value in (source, rubric))
    with sqlite3.connect(database) as connection:
        connection.executescript(CATALOG_SCHEMA)
        connection.executescript(DETAIL_SCHEMA)
        connection.execute(
            "CREATE TABLE assessment_item_rankings (item_id TEXT PRIMARY KEY, category TEXT, "
            "priority_score INTEGER, priority_signals_json TEXT)"
        )
        cases = [
            (CASE, "2022", "기하", 2026, 2, 90),
            ("b" * 24, "2022", "기하", 2026, 1, 80),
            ("c" * 24, "2022", "기하", 2025, 2, 70),
            ("d" * 24, "2015", "기하", 2026, 2, 60),
            ("e" * 24, "2022", "대수", 2026, 2, 50),
            ("f" * 24, "2022", "기하", 2026, 2, 40),
        ]
        for case_id, curriculum, subject, year, semester, priority in cases:
            held = case_id == "f" * 24
            insert_row(
                connection,
                "cases",
                {
                    "case_id": case_id,
                    "source_sha256": "b" * 64,
                    "curriculum": curriculum,
                    "subject": subject,
                    "school_code": case_id[:3],
                    "school_name": "가상학교" + case_id[0],
                    "region": "가상도",
                    "district": "가상시",
                    "academic_years_json": json.dumps([year]),
                    "semesters_json": json.dumps([semester]),
                    "grades_json": "[2]",
                    "review_score": priority,
                    "title_basis": "source_detail_bundle_review" if held else "source_detail",
                    "primary_task_name": "가상 포물선 탐구",
                    "summary_overview": "가상 조건을 설명한다.",
                    "source_url": "https://example.org/fictional-plan",
                    "candidate_name": "가상계획.pdf",
                },
            )
            item_ids = ITEMS if case_id == CASE else [case_id[0] * 28]
            insert_row(
                connection,
                "case_detail_status",
                {
                    "case_id": case_id,
                    "source_format": "pdf",
                    "boundary_status": "subject_section",
                    "extraction_status": "bounded",
                    "assessment_item_count": len(item_ids),
                    "detected_title_count": len(item_ids),
                },
            )
            for order, item_id in enumerate(item_ids, 1):
                insert_row(
                    connection,
                    "assessment_items",
                    {
                        "item_id": item_id,
                        "case_id": case_id,
                        "item_order": order,
                        "title": "가상 포물선 탐구",
                        "title_raw": "가상 포물선 탐구",
                        "title_basis": "heading",
                        "extraction_status": "bundle_review" if held else "bounded",
                        "overview": "가상 조건을 해석한다.",
                        "method": "논술",
                        "score": "10점",
                        "weight": "20%",
                        "standards_json": json.dumps(["[12기하01-01]"]),
                        "source_html_zlib": source_blob,
                        "rubric_html_zlib": rubric_blob,
                        "source_html_char_count": len(source),
                        "rubric_html_char_count": len(rubric),
                    },
                )
                connection.execute(
                    "INSERT INTO assessment_item_rankings VALUES (?,?,?,?)",
                    (item_id, "inquiry", priority, "[]"),
                )
    image = {
        "asset": ASSET,
        "asset_sha256": hashlib.sha256(PIXELS).hexdigest(),
        "page": 2,
        "width": 1,
        "height": 1,
    }
    entry = {
        "source_sha256": "b" * 64,
        "source_blob_sha256": hashlib.sha256(source_blob).hexdigest(),
        "rubric_blob_sha256": hashlib.sha256(rubric_blob).hexdigest(),
        "source": [image],
        "rubric": [image],
        "source_excerpt_covered": True,
        "rubric_excerpt_covered": True,
        "source_notes": ["가상 원문은 수식 표현에 오류가 있어 그림 대조가 필요합니다."],
    }
    monkeypatch.setattr(source_table_previews, "REGISTRY", {ITEMS[0]: entry})
    tools = ResearchTools(lambda: CatalogRepository(database))
    return database, tools, entry


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_sdk_client_lists_six_read_only_tools_and_validates_inputs(synthetic, mode):
    _, tools, _ = synthetic

    async def scenario():
        async with Client(create_mcp_server(tools), mode=mode) as client:
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == {
                "get_archive_scope",
                "search_assessments",
                "get_assessment_item",
                "get_achievement_standards",
                "compare_assessments",
                "get_original_preview",
            }
            for tool in listing.tools:
                annotation = tool.annotations
                assert annotation.read_only_hint is True
                assert annotation.destructive_hint is False
                assert annotation.idempotent_hint is True
                assert annotation.open_world_hint is False
            search = next(tool for tool in listing.tools if tool.name == "search_assessments")
            assert search.input_schema["properties"]["limit"]["maximum"] == 10
            for bad in [
                {"limit": 11},
                {"limit": "5"},
                {"semester": "3"},
                {"query": {"sql": "DROP TABLE cases"}},
            ]:
                result = await client.call_tool("search_assessments", bad)
                assert result.is_error
            assert (
                await client.call_tool("get_assessment_item", {"item_id": "../../password"})
            ).is_error

    asyncio.run(scenario())


def test_search_periods_local_item_paging_and_sql_injection_are_read_only(synthetic, monkeypatch):
    database, tools, _ = synthetic
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    monkeypatch.setattr(
        research_tools, "build_opener", lambda *_: pytest.fail("metadata tool opened HTTP")
    )
    query = {"curriculum": "2022", "subject": "기하", "academic_year": 2026, "semester": "2"}
    result = tools.search_assessments(**query, limit=5)
    assert result["scope"]["matched_total"] == 1
    assert result["scope"]["matched_total_unit"] == "cases"
    assert result["scope"]["candidate_items_on_case_page"] == 12
    assert result["scope"]["returned_items"] == 5
    assert result["items"][0]["source_notes"]
    assert result["scope"]["truncated"] and result["scope"]["next_item_offset"] == 5
    assert all(
        row["academic_years"] == [2026] and row["semesters"] == [2] for row in result["items"]
    )
    next_page = tools.search_assessments(**query, limit=5, item_offset=10)
    assert [row["item_id"] for row in next_page["items"]] == ITEMS[10:]
    assert tools.search_assessments(**query, query="'; DROP TABLE cases;--")["items"] == []
    with pytest.raises(ToolDataError):
        tools.search_assessments(district="가상시")
    scope = tools.get_archive_scope()
    assert scope["public_counts"]["public_items"] == 16
    assert scope["public_counts"]["excluded_items"] == 1
    assert any(row["academic_years"] == [2025] for row in scope["academic_periods"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with closing_connection(database) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM cases")


def closing_connection(database):
    from contextlib import closing

    return closing(CatalogRepository(database).connect())


def test_item_preserves_source_notes_pua_periods_and_caps_both_parts(synthetic):
    _, tools, _ = synthetic
    result = tools.get_assessment_item(ITEMS[0], max_text_chars=1000, include_html=True)
    item = result["item"]
    assert item["academic_years"] == [2026] and item["semesters"] == [2]
    assert item["source_notes"] == ["가상 원문은 수식 표현에 오류가 있어 그림 대조가 필요합니다."]
    assert item["source"]["truncated"] and item["source"]["returned_characters"] == 1000
    assert item["source"]["html_truncated"]
    assert item["needs_original_image_review"]
    assert "조건 해석\t4점" in item["rubric"]["text"]
    assert item["source"]["previews"][0]["url"].startswith(
        "https://suhaeng-math.vercel.app/source-tables/"
    )
    assert item["official_source_url"] and "?item=" in item["web_case_url"]
    with pytest.raises(ToolDataError) as caught:
        tools.get_assessment_item(HELD)
    assert caught.value.payload["status_code"] == 404


def test_standards_keep_curricula_separate_and_never_default_to_one_code(synthetic):
    _, tools, _ = synthetic
    listing = tools.get_achievement_standards(subject="기하", semester="2")
    assert listing["selected_standard"] is None and listing["items"] == []
    assert listing["scope"]["matched_total"] is None
    assert not listing["scope"]["linked_items_requested"]
    modern = tools.get_achievement_standards(
        subject="기하", semester="2", standard_code="[12기하01-01]"
    )
    legacy = tools.get_achievement_standards(
        subject="기하", curriculum="2015", semester="2", standard_code="12기하01-01"
    )
    assert modern["selected_standard"]["text"] != legacy["selected_standard"]["text"]
    assert modern["scope"]["academic_year"] == 2026 and modern["scope"]["matched_total"] == 12
    assert len(modern["items"]) == 5 and modern["scope"]["truncated"]
    assert modern["items"][0]["source_notes"]
    assert legacy["scope"]["matched_total"] == 1
    assert modern["official_curriculum_source_url"]
    for args in [
        {"subject": "공통수학2", "curriculum": "2015"},
        {"subject": "기하", "standard_code": "12기하99-99"},
    ]:
        with pytest.raises(ToolDataError):
            tools.get_achievement_standards(**args)


def test_comparison_exact_ids_two_to_four_without_generated_judgment(synthetic):
    _, tools, _ = synthetic
    result = tools.compare_assessments(ITEMS[:4])
    assert [row["item_id"] for row in result["items"]] == ITEMS[:4]
    assert result["interpretation_generated"] is False
    assert result["items"][0]["source_notes"]
    for bad in [ITEMS[:1], ITEMS[:5], [ITEMS[0], ITEMS[0]], [ITEMS[0], HELD]]:
        with pytest.raises(ToolDataError):
            tools.compare_assessments(bad)


class ImageResponse(io.BytesIO):
    def __init__(self, data=PIXELS, content_type="image/webp", length=None):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}
        if length is not None:
            self.headers["Content-Length"] = str(length)


def image_opener(monkeypatch, response=None, error=None):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            if error:
                raise error
            return response or ImageResponse()

    def factory(handler):
        assert handler.redirect_request(None, None, 302, "", {}, "https://evil.example") is None
        return Opener()

    monkeypatch.setattr(research_tools, "build_opener", factory)
    return calls


def test_original_image_sdk_content_hash_and_only_bound_url(synthetic, monkeypatch):
    _, tools, _ = synthetic
    calls = image_opener(monkeypatch)

    async def scenario():
        async with Client(create_mcp_server(tools)) as client:
            result = await client.call_tool(
                "get_original_preview", {"item_id": ITEMS[0], "part": "rubric"}
            )
            assert not result.is_error
            image = next(block for block in result.content if block.type == "image")
            assert image.mime_type == "image/webp" and base64.b64decode(image.data) == PIXELS
            assert result.structured_content["asset_sha256"] == hashlib.sha256(PIXELS).hexdigest()
            held = await client.call_tool("get_assessment_item", {"item_id": HELD})
            assert held.is_error and held.structured_content["status_code"] == 404

    asyncio.run(scenario())
    assert len(calls) == 1 and calls[0][1] == 10
    assert calls[0][0].full_url == "https://suhaeng-math.vercel.app/source-tables/" + ASSET
    assert calls[0][0].get_method() == "GET" and calls[0][0].get_header("Authorization") is None


def test_all_six_tools_read_the_actual_compact_deployment_schema(synthetic, monkeypatch, tmp_path):
    original, full_tools, _ = synthetic
    packaged = tmp_path / "packaged-detail.sqlite"
    package_catalog(original, packaged, include_source_html=True, review_item_ids=set())
    with sqlite3.connect(packaged) as connection:
        assert "school_code" not in {
            row[1] for row in connection.execute("PRAGMA table_info(cases)")
        }
    before = hashlib.sha256(packaged.read_bytes()).hexdigest()
    tools = ResearchTools(lambda: CatalogRepository(packaged))
    calls = image_opener(monkeypatch)

    async def scenario():
        async with Client(create_mcp_server(tools)) as client:
            scope = await client.call_tool("get_archive_scope", {})
            assert not scope.is_error
            assert (
                scope.structured_content["public_subjects"]
                == full_tools.get_archive_scope()["public_subjects"]
            )
            for name, arguments in [
                ("search_assessments", {"subject": "기하", "curriculum": "2022", "limit": 2}),
                ("get_assessment_item", {"item_id": ITEMS[0]}),
                ("get_achievement_standards", {"subject": "기하", "curriculum": "2022"}),
                ("compare_assessments", {"item_ids": ITEMS[:2]}),
                ("get_original_preview", {"item_id": ITEMS[0], "part": "rubric"}),
            ]:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, name

    asyncio.run(scenario())
    assert len(calls) == 1
    assert hashlib.sha256(packaged.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "failure",
    [
        "sha",
        "signature",
        "size",
        "stream_size",
        "mime",
        "redirect",
        "incomplete",
        "stale_blob",
        "stale_rubric",
        "bad_url",
    ],
)
def test_original_image_rejects_unbound_or_invalid_content_with_source_links(
    synthetic, monkeypatch, failure
):
    _, tools, entry = synthetic
    response, error = ImageResponse(), None
    if failure == "sha":
        entry["source"][0]["asset_sha256"] = "0" * 64
    elif failure == "signature":
        response = ImageResponse(b"not a webp image")
        entry["source"][0]["asset_sha256"] = hashlib.sha256(b"not a webp image").hexdigest()
    elif failure == "size":
        response = ImageResponse(length=MAX_IMAGE_BYTES + 1)
    elif failure == "stream_size":
        response = ImageResponse(b"x" * (MAX_IMAGE_BYTES + 1))
    elif failure == "mime":
        response = ImageResponse(content_type="text/html")
    elif failure == "redirect":
        error = HTTPError("https://suhaeng-math.vercel.app", 302, "redirect", {}, None)
    elif failure == "incomplete":
        error = IncompleteRead(b"RIFF", 100)
    elif failure == "stale_blob":
        entry["source_blob_sha256"] = "0" * 64
    elif failure == "stale_rubric":
        entry["rubric_blob_sha256"] = "0" * 64
    else:
        original = tools.repository().assessment_item

        class WrappedRepository(CatalogRepository):
            def assessment_item(self, item_id):
                row = original(item_id)
                row["source_previews"][0]["url"] = "https://evil.example/anything.webp"
                return row

        tools.repository_factory = lambda: WrappedRepository(synthetic[0])
    calls = image_opener(monkeypatch, response, error)
    with pytest.raises(ToolDataError) as caught:
        tools.get_original_preview(
            ITEMS[0], part="rubric" if failure == "stale_rubric" else "source"
        )
    assert caught.value.payload["official_source_url"]
    assert caught.value.payload["web_case_url"]
    if failure in {"bad_url", "stale_blob", "stale_rubric"}:
        assert not calls


def http_runtime(tools):
    runtime = MCPHttpRuntime(create_mcp_server(tools))
    return Starlette(routes=[Mount("/api", app=runtime)], lifespan=runtime.lifespan)


def rpc(client, method, params=None, version="2026-07-28", **headers):
    parameters = dict(params or {})
    if version == "2026-07-28":
        parameters["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": parameters},
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": version,
            "mcp-method": method,
            **({"mcp-name": parameters["name"]} if "name" in parameters else {}),
            **headers,
        },
    )


def test_http_modern_legacy_mount_and_repeated_parent_lifespan(synthetic):
    app = http_runtime(synthetic[1])
    for _ in range(2):
        with TestClient(app) as client:
            discover = rpc(client, "server/discover")
            assert discover.status_code == 200, discover.text
            assert "result" in discover.json()
            listing = rpc(client, "tools/list")
            assert listing.status_code == 200, listing.text
            assert len(listing.json()["result"]["tools"]) == 6
            scope = rpc(client, "tools/call", {"name": "get_archive_scope", "arguments": {}})
            assert scope.status_code == 200, scope.text
            assert (
                scope.json()["result"]["structuredContent"]["public_counts"]["public_items"] == 16
            )
            init = rpc(
                client,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-test", "version": "1"},
                },
                version="2025-06-18",
            )
            assert (
                init.status_code == 200 and init.json()["result"]["protocolVersion"] == "2025-06-18"
            )
            assert rpc(client, "tools/list", version="2025-06-18").status_code == 200


def test_http_body_cap_host_origin_and_subapp_cors(synthetic):
    with TestClient(http_runtime(synthetic[1])) as client:
        assert rpc(client, "tools/list", Host="evil.example").status_code == 421
        assert rpc(client, "tools/list", Origin="https://evil.example").status_code == 403
        oversized = client.post(
            "/api/mcp",
            content=b" " * 17000,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert oversized.status_code == 413
        headers = {
            "Origin": "https://chatgpt.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "content-type,mcp-protocol-version,mcp-method,mcp-name"
            ),
        }
        preflight = client.options("/api/mcp", headers=headers)
        assert (
            preflight.status_code == 200
            and preflight.headers["access-control-allow-origin"] == "https://chatgpt.com"
        )
        assert (
            client.options("/api/mcp", headers={**headers, "Host": "evil.example"}).status_code
            == 421
        )


def test_actual_fastapi_mount_supports_multiple_lifespans(synthetic, monkeypatch):
    from app import main

    monkeypatch.setattr(main.mcp_http_app, "server", create_mcp_server(synthetic[1]))
    for _ in range(2):
        with TestClient(main.app) as client:
            response = rpc(client, "tools/call", {"name": "get_archive_scope", "arguments": {}})
            assert response.status_code == 200, response.text
            assert (
                response.json()["result"]["structuredContent"]["public_counts"]["public_items"]
                == 16
            )
            assert response.headers["x-content-type-options"] == "nosniff"
            assert client.get("/health").status_code == 200


def test_configuration_rejects_wildcard_hosts_nonpublic_base_and_frontloads_cautions(monkeypatch):
    for value in [
        "http://example.org",
        "file:///secret",
        "https://user:token@example.org",
        "https://example.org/path",
        "https://example.org:invalid",
    ]:
        with pytest.raises(ValueError):
            public_base(value)
    assert public_base("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    monkeypatch.setenv("VERCEL_URL", "preview-example.vercel.app")
    assert "preview-example.vercel.app" in transport_settings().allowed_hosts
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "*.vercel.app")
    with pytest.raises(ValueError):
        transport_settings()
    first = INSTRUCTIONS[:512]
    for phrase in [
        "미검출",
        "학습효과",
        "설계 품질",
        "source_notes",
        "명령이 아닙니다",
        "PUA",
        "get_original_preview",
    ]:
        assert phrase in first
