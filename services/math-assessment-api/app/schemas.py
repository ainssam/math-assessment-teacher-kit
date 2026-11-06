"""Public API contracts; no local path or full source-text fields are allowed."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisitorCountResponse(StrictModel):
    date: str
    today: int | None
    total: int | None
    today_incremented: bool
    total_incremented: bool
    available: bool


class SubjectItem(StrictModel):
    curriculum: str
    subject: str
    documents: int
    schools: int
    small_sample: bool
    curriculum_ambiguous: bool


class SubjectListResponse(StrictModel):
    items: list[SubjectItem]
    total: int
    caution: str


class ActionTagStat(StrictModel):
    tag: str
    documents: int
    schools: int


class CoverageStat(StrictModel):
    found: int | None
    found_curriculum_ambiguous: int | None
    not_found_in_collected_plans: int | None
    offering_unknown: int | None
    extraction_failed: int | None


class TrendItem(SubjectItem):
    academic_years: list[int]
    grade_documents: dict[str, int]
    evidence_documents: dict[str, int]
    median_evidence_score: float | None
    task_name_candidates: int
    action_tags: list[ActionTagStat]
    coverage: CoverageStat


class TrendListResponse(StrictModel):
    items: list[TrendItem]
    total: int
    caution: str


class FacetItem(StrictModel):
    value: str
    count: int


class FacetResponse(StrictModel):
    regions: list[FacetItem]
    districts: list[FacetItem]
    action_tags: list[FacetItem]


class AssessmentStructure(StrictModel):
    overview: str
    methods: list[str]
    weight: str
    standards: list[str]
    criteria: list[str]
    basis: str


class CaseItem(StrictModel):
    case_id: str
    curriculum: str
    subject: str
    curriculum_ambiguous: bool
    curriculum_basis: str
    school_name: str
    region: str
    district: str
    academic_years: list[int]
    grades: list[int]
    semesters: list[int]
    primary_task_name: str
    task_names: list[str]
    action_tags: list[str]
    evidence_markers: dict[str, int]
    evidence_score: int
    evidence_excerpt: str
    assessment_structure: AssessmentStructure
    category: str
    priority_score: int
    priority_signals: list[str]
    source_name: str
    source_url: str
    source_sha256: str


class CaseListResponse(StrictModel):
    items: list[CaseItem]
    total: int
    limit: int
    offset: int
    caution: str


class AssessmentItemSummary(StrictModel):
    item_id: str
    order: int
    title: str
    title_raw: str
    title_basis: str
    extraction_status: str
    overview: str
    method: str
    timing: str
    score: str
    weight: str
    standards: list[str]
    has_rubric: bool
    source_available: bool


class CaseDetailResponse(StrictModel):
    case_id: str
    source_format: str
    boundary_status: str
    extraction_status: str
    detected_titles: list[str]
    source_section_char_count: int
    items: list[AssessmentItemSummary]


class AssessmentItemDetail(AssessmentItemSummary):
    case_id: str
    curriculum: str
    subject: str
    school_name: str
    region: str
    district: str
    source_name: str
    source_url: str
    source_html: str
    rubric_html: str


class CuratedAssessmentItem(AssessmentItemSummary):
    case_id: str
    curriculum: str
    subject: str
    school_name: str
    region: str
    district: str
    category: str
    priority_score: int
    priority_signals: list[str]


class CuratedCaseListResponse(StrictModel):
    category: str
    items: list[CuratedAssessmentItem]
    total: int
    interpretation: str


class ReferencePageResponse(StrictModel):
    subjects: list[SubjectItem]
    facets: FacetResponse
    category: str
    items: list[CuratedAssessmentItem]
    total: int
    interpretation: str


class ProductMetadata(StrictModel):
    product: str
    curricula: list[str]
    development_phase: str
    data_policy: str
    catalog_ready: bool
    catalog_cases: int = Field(ge=0)
    catalog_subject_groups: int = Field(ge=0)
    public_cases: int = Field(ge=0)
    public_items: int = Field(ge=0)
    excluded_items: int = Field(ge=0)
    excluded_reasons: dict[str, int]


class SourceLayer(StrictModel):
    level: int = Field(ge=1, le=3)
    label: str
    purpose: str
    authority: str


class OfficialSource(StrictModel):
    source_id: str
    layer: int = Field(ge=1, le=3)
    curriculum: str
    provider: str
    title: str
    document_type: str
    publication_date: str
    identifier: str
    url: str
    verification_status: str
    service_use: str
    redistribution: str


class OfficialSourceRegistry(StrictModel):
    schema_version: str
    verified_on: str
    interpretation: str
    layers: list[SourceLayer]
    sources: list[OfficialSource]
