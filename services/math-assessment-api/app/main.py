"""읽기·설계 기능을 위한 수학 수행평가 API의 독립 진입점."""

import json
import os
from typing import Annotated, Final, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response

from app.mcp_server import http as mcp_http_app
from app.mcp_server import mcp_lifespan
from app.repository import CatalogRepository
from app.request_guard import client_key, limiter
from app.schemas import (
    AssessmentItemDetail,
    CaseDetailResponse,
    CaseItem,
    CaseListResponse,
    CuratedCaseListResponse,
    DesignReferenceResponse,
    FacetResponse,
    OfficialSourceRegistry,
    ProductMetadata,
    ReferencePageResponse,
    StandardReferenceResponse,
    SubjectListResponse,
    TrendListResponse,
    VisitorCountResponse,
)
from app.settings import (
    catalog_database_path,
    detail_catalog_database_path,
    official_source_registry_path,
)
from app.standard_catalog import REGISTRIES
from app.visitor_counter import visitor_counts

SERVICE_NAME: Final = "math-assessment-api"
SERVICE_VERSION: Final = "0.3.0"
INTERPRETATION_CAUTION: Final = (
    "평가계획에서 과목이 발견되지 않았다는 사실은 학교가 과목을 개설하지 않았다는 뜻이 아닙니다."
)

app = FastAPI(
    title="2026 수학 수행평가 아이디어 아카이브 API",
    description="전국 수행평가 경향 탐색과 교사 설계를 지원하는 근거 기반 API",
    version=SERVICE_VERSION,
    lifespan=mcp_lifespan,
    # Interactive API docs are useful in local review, but do not need to be a
    # public discovery surface in the production teacher service.
    docs_url=None if os.environ.get("VERCEL") else "/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    """API 응답이 브라우저에서 문서나 프레임으로 오용되지 않도록 제한한다."""
    path = request.url.path
    if path.startswith("/api/v1/") or path.rstrip("/") == "/api/mcp":
        if path.rstrip("/") == "/api/mcp":
            limit = 70
        elif path.endswith("/detail") or "/assessment-items/" in path:
            limit = 40
        elif path in {
            "/api/v1/cases",
            "/api/v1/references",
            "/api/v1/design-references",
            "/api/v1/standard-references",
        }:
            limit = 70
        elif path == "/api/v1/visitors":
            limit = 12
        else:
            limit = 150
        if not limiter.allow(client_key(dict(request.headers), path), limit=limit):
            return Response(
                content=json.dumps(
                    {"detail": "요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요."},
                    ensure_ascii=False,
                ),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.get("/health", tags=["system"])
@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


@app.post("/api/v1/visitors", response_model=VisitorCountResponse, tags=["system"])
def visitors(
    request: Request,
    increment_today: bool = False,
    increment_total: bool = False,
) -> dict[str, object]:
    """개인 식별정보 없이 브라우저가 요청한 숫자 카운터만 갱신한다."""
    origin = request.headers.get("origin", "").rstrip("/")
    counter_origin = os.environ.get("MATH_ASSESSMENT_COUNTER_ORIGIN", "").rstrip("/")
    trusted_visit = bool(counter_origin) and origin == counter_origin
    return visitor_counts(
        increment_today=trusted_visit and increment_today,
        increment_total=trusted_visit and increment_total,
    )


def repository() -> CatalogRepository:
    return CatalogRepository(catalog_database_path())


def detail_repository() -> CatalogRepository:
    return CatalogRepository(detail_catalog_database_path())


def ready_repository() -> CatalogRepository:
    value = repository()
    if not value.ready:
        raise HTTPException(status_code=503, detail="발행 데이터가 아직 준비되지 않았습니다.")
    return value


def ready_detail_repository() -> CatalogRepository:
    value = detail_repository()
    if not value.ready:
        raise HTTPException(
            status_code=503,
            detail="평가계획 원문 자료가 아직 준비되지 않았습니다.",
        )
    return value


def require_region_for_district(region: str | None, district: str | None) -> None:
    if district and not region:
        raise HTTPException(
            status_code=422,
            detail="시군구를 선택하려면 시도를 함께 지정해야 합니다.",
        )


def official_source_registry() -> dict[str, object]:
    path = official_source_registry_path()
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail="공식 출처 레지스트리가 아직 준비되지 않았습니다.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=503,
            detail="공식 출처 레지스트리를 읽지 못했습니다.",
        ) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=503,
            detail="공식 출처 레지스트리 형식이 올바르지 않습니다.",
        )
    return payload


@app.get("/api/v1/meta", response_model=ProductMetadata, tags=["system"])
def product_metadata() -> dict[str, object]:
    """화면이 사용하는 비민감 제품 범위만 제공한다."""
    catalog = repository()
    cases, subjects = catalog.catalog_counts()
    publication = catalog.publication_counts()
    return {
        "product": "2026 수학 수행평가 아이디어 아카이브",
        "curricula": ["2015 개정", "2022 개정"],
        "development_phase": "수학 수행평가 원문 탐색기",
        "data_policy": "수학 수행평가 구간만 원문 표 구조로 제공하고 전체 문서는 제외",
        "catalog_ready": catalog.ready,
        "catalog_cases": cases,
        "catalog_subject_groups": subjects,
        **publication,
    }


@app.get("/api/v1/sources", response_model=OfficialSourceRegistry, tags=["sources"])
def sources() -> dict[str, object]:
    """공식 기준과 학교 사례의 권위·용도를 분리한 출처 레지스트리다."""
    return official_source_registry()


@app.get("/api/v1/subjects", response_model=SubjectListResponse, tags=["catalog"])
def subjects(
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022|shared)$")] = None,
) -> dict[str, object]:
    items = ready_repository().subjects(curriculum)
    return {"items": items, "total": len(items), "caution": INTERPRETATION_CAUTION}


@app.get("/api/v1/trends", response_model=TrendListResponse, tags=["catalog"])
def trends(
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022|shared)$")] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
) -> dict[str, object]:
    items = ready_repository().trends(curriculum, subject)
    return {"items": items, "total": len(items), "caution": INTERPRETATION_CAUTION}


@app.get("/api/v1/cases", response_model=CaseListResponse, tags=["catalog"])
def cases(
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022|shared)$")] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    district: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    query: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    semester: Annotated[Literal["1", "2", "unknown"] | None, Query()] = None,
    academic_year: Annotated[int | None, Query(ge=2000, le=2099)] = None,
    include_ambiguous: bool = True,
    limit: Annotated[int, Query(ge=1, le=30)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    require_region_for_district(region, district)
    items, total = ready_repository().cases(
        curriculum=curriculum,
        subject=subject,
        tag=tag,
        region=region,
        district=district,
        source_status="confirmed",
        query=query,
        include_ambiguous=include_ambiguous,
        limit=limit,
        offset=offset,
        semester=semester,
        academic_year=academic_year,
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "caution": "증거 완결성 점수는 수행평가 설계 품질에 대한 최종 판단이 아닙니다.",
    }


@app.get("/api/v1/curated", response_model=CuratedCaseListResponse, tags=["catalog"])
def curated_cases(
    category: Annotated[
        str,
        Query(pattern="^(inquiry|modeling|problem|presentation|portfolio|reading)$"),
    ] = "inquiry",
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022)$")] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    district: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
) -> dict[str, object]:
    require_region_for_district(region, district)
    catalog = ready_repository()
    items = catalog.curated_items(
        curriculum=curriculum,
        subject=subject,
        region=region,
        district=district,
        category=category,
        limit=limit,
    )
    return {
        "category": category,
        "items": items,
        "total": catalog.curated_total(
            curriculum=curriculum,
            subject=subject,
            region=region,
            district=district,
            category=category,
        ),
        "interpretation": (
            "공개 평가계획에서 과제명, 성취기준, 채점기준, 평가방법과 과정 증거가 "
            "함께 확인되는 사례를 설계 참고 우선순위로 정리했습니다. 학교나 교사의 서열이 아닙니다."
        ),
    }


@app.get("/api/v1/references", response_model=ReferencePageResponse, tags=["catalog"])
def references(
    category: Annotated[
        str,
        Query(pattern="^(inquiry|modeling|problem|presentation|portfolio|reading)$"),
    ] = "inquiry",
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022)$")] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    district: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 30,
) -> dict[str, object]:
    require_region_for_district(region, district)
    catalog = ready_repository()
    items = catalog.curated_items(
        curriculum=curriculum,
        subject=subject,
        region=region,
        district=district,
        category=category,
        limit=limit,
    )
    return {
        "subjects": catalog.subjects(),
        "facets": catalog.curated_facets(
            curriculum=curriculum,
            subject=subject,
            region=region,
            category=category,
        ),
        "category": category,
        "items": items,
        "total": catalog.curated_total(
            curriculum=curriculum,
            subject=subject,
            region=region,
            district=district,
            category=category,
        ),
        "interpretation": (
            "공개 평가계획에서 과제명, 성취기준, 채점기준, 평가방법과 과정 증거가 함께 "
            "확인되는 사례를 설계 참고 우선순위로 정리했습니다. 학교나 교사의 서열이 아닙니다."
        ),
    }


@app.get("/api/v1/facets", response_model=FacetResponse, tags=["catalog"])
def facets(
    curriculum: Annotated[str | None, Query(pattern="^(2015|2022|shared)$")] = None,
    subject: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    region: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    semester: Annotated[Literal["1", "2", "unknown"] | None, Query()] = None,
    academic_year: Annotated[int | None, Query(ge=2000, le=2099)] = None,
) -> dict[str, object]:
    return ready_repository().facets(curriculum, subject, region, semester, academic_year)


@app.get("/api/v1/design-references", response_model=DesignReferenceResponse, tags=["catalog"])
def design_references(
    topic: Annotated[str, Query(max_length=24, pattern=r"^[a-z-]*$")] = "",
    method: Annotated[str, Query(max_length=24, pattern=r"^[a-z-]*$")] = "",
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> dict[str, object]:
    return ready_repository().design_references(topic, method, limit, offset)


@app.get("/api/v1/standard-references", response_model=StandardReferenceResponse, tags=["catalog"])
def standard_references(
    subject: Annotated[str | None, Query(max_length=40)] = None,
    standard: Annotated[str, Query(max_length=32)] = "",
    semester: Annotated[Literal["1", "2"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
    offset: Annotated[int, Query(ge=0, le=30_000)] = 0,
    curriculum: Annotated[Literal["2015", "2022"], Query()] = "2022",
) -> dict[str, object]:
    subject = subject or ("미적분Ⅰ" if curriculum == "2022" else "수학")
    if subject not in REGISTRIES[curriculum]["subjects"]:
        raise HTTPException(
            status_code=422, detail="선택한 교육과정에 해당하는 수학 과목을 골라 주세요."
        )
    return ready_repository().standard_references(
        subject, standard, semester, limit, offset, curriculum
    )


@app.get("/api/v1/cases/{case_id}", response_model=CaseItem, tags=["catalog"])
def case(case_id: Annotated[str, Path(pattern="^[0-9a-f]{24}$")]) -> dict[str, object]:
    item = ready_repository().case(case_id)
    if item is None or item["assessment_structure"]["basis"] != "source_detail":
        raise HTTPException(status_code=404, detail="사례를 찾을 수 없습니다.")
    return item


@app.get(
    "/api/v1/cases/{case_id}/detail",
    response_model=CaseDetailResponse,
    tags=["catalog"],
)
def case_detail(
    case_id: Annotated[str, Path(pattern="^[0-9a-f]{24}$")],
) -> dict[str, object]:
    detail = ready_detail_repository().case_detail(case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="수행평가 원문 상세를 찾을 수 없습니다.")
    return detail


@app.get(
    "/api/v1/assessment-items/{item_id}",
    response_model=AssessmentItemDetail,
    tags=["catalog"],
)
def assessment_item(
    item_id: Annotated[str, Path(pattern="^[0-9a-f]{28}$")],
) -> dict[str, object]:
    item = ready_detail_repository().assessment_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="수행평가 항목을 찾을 수 없습니다.")
    return item


# Keep the SDK transport after all REST routes so /api/v1 remains unchanged.
app.mount("/api", mcp_http_app)
