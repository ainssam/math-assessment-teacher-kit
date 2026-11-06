export type Curriculum = "2015" | "2022" | "shared";

export type SubjectItem = {
  curriculum: Curriculum;
  subject: string;
  documents: number;
  schools: number;
  small_sample: boolean;
  curriculum_ambiguous: boolean;
};

export type ActionTagStat = {
  tag: string;
  documents: number;
  schools: number;
};

export type TrendItem = SubjectItem & {
  academic_years: number[];
  grade_documents: Record<"1" | "2" | "3", number>;
  evidence_documents: {
    rubric: number;
    achievement_standard: number;
    weight_or_points: number;
    assessment_method: number;
  };
  median_evidence_score: number | null;
  task_name_candidates: number;
  action_tags: ActionTagStat[];
  coverage: {
    found: number | null;
    found_curriculum_ambiguous: number | null;
    not_found_in_collected_plans: number | null;
    offering_unknown: number | null;
    extraction_failed: number | null;
  };
};

export type SubjectListResponse = {
  items: SubjectItem[];
  total: number;
  caution: string;
};

export type TrendListResponse = {
  items: TrendItem[];
  total: number;
  caution: string;
};

export type CaseItem = {
  case_id: string;
  curriculum: Curriculum;
  subject: string;
  curriculum_ambiguous: boolean;
  curriculum_basis: string;
  school_name: string;
  region: string;
  district: string;
  academic_years: number[];
  grades: number[];
  semesters: number[];
  primary_task_name: string;
  task_names: string[];
  action_tags: string[];
  evidence_markers: {
    rubric: number;
    achievement_standard: number;
    weight_or_points: number;
    assessment_method: number;
  };
  evidence_score: number;
  evidence_excerpt: string;
  assessment_structure: {
    overview: string;
    methods: string[];
    weight: string;
    standards: string[];
    criteria: string[];
    basis: "table" | "heading" | "section" | "area" | "context" | "missing" | "source_detail" | "source_detail_bundle_review" | "source_detail_bundle_review_table_title";
  };
  category: string;
  priority_score: number;
  priority_signals: string[];
  source_name: string;
  source_url: string;
  source_sha256: string;
};

export type CuratedCaseListResponse = {
  category: string;
  items: CuratedAssessmentItem[];
  total: number;
  interpretation: string;
};

export type ReferencePageResponse = CuratedCaseListResponse & {
  subjects: SubjectItem[];
  facets: FacetResponse;
};

export type CaseListResponse = {
  items: CaseItem[];
  total: number;
  limit: number;
  offset: number;
  caution: string;
};

export type AssessmentItemSummary = {
  item_id: string;
  order: number;
  title: string;
  title_raw: string;
  title_basis: string;
  extraction_status: string;
  overview: string;
  method: string;
  timing: string;
  score: string;
  weight: string;
  standards: string[];
  has_rubric: boolean;
  source_available: boolean;
};

export type CuratedAssessmentItem = AssessmentItemSummary & {
  case_id: string;
  curriculum: Curriculum;
  subject: string;
  school_name: string;
  region: string;
  district: string;
  category: string;
  priority_score: number;
  priority_signals: string[];
};

export type CaseDetailResponse = {
  case_id: string;
  source_format: string;
  boundary_status: string;
  extraction_status: string;
  detected_titles: string[];
  source_section_char_count: number;
  items: AssessmentItemSummary[];
};

export type AssessmentItemDetail = AssessmentItemSummary & {
  case_id: string;
  curriculum: Curriculum;
  subject: string;
  school_name: string;
  region: string;
  district: string;
  source_name: string;
  source_url: string;
  source_html: string;
  rubric_html: string;
};

export type FacetResponse = {
  regions: Array<{ value: string; count: number }>;
  districts: Array<{ value: string; count: number }>;
  action_tags: Array<{ value: string; count: number }>;
};

export type SourceLayer = {
  level: 1 | 2 | 3;
  label: string;
  purpose: string;
  authority: string;
};

export type OfficialSource = {
  source_id: string;
  layer: 1 | 2 | 3;
  curriculum: string;
  provider: string;
  title: string;
  document_type: string;
  publication_date: string;
  identifier: string;
  url: string;
  verification_status: string;
  service_use: string;
  redistribution: string;
};

export type OfficialSourceRegistry = {
  schema_version: string;
  verified_on: string;
  interpretation: string;
  layers: SourceLayer[];
  sources: OfficialSource[];
};

export type ProductMetadata = {
  product: string;
  curricula: string[];
  development_phase: string;
  data_policy: string;
  catalog_ready: boolean;
  catalog_cases: number;
  catalog_subject_groups: number;
  public_cases: number;
  public_items: number;
  excluded_items: number;
  excluded_reasons: Record<string, number>;
};

export function apiParameters(values: Record<string, string | number | boolean | undefined>) {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") parameters.set(key, String(value));
  }
  return parameters.toString();
}

const TRANSIENT_RESPONSE_STATUSES = new Set([500, 502, 503, 504]);

function waitForRetry(milliseconds: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The operation was aborted", "AbortError"));
      return;
    }
    const timeout = window.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    function abort() {
      window.clearTimeout(timeout);
      reject(new DOMException("The operation was aborted", "AbortError"));
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export async function fetchCatalog<T>(path: string, signal?: AbortSignal): Promise<T> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await fetch(`/api/v1/${path}`, {
      signal,
      headers: { Accept: "application/json" },
    });
    if (response.ok) return response.json() as Promise<T>;

    const payload = await response.json().catch(() => null);
    const mayRetry = TRANSIENT_RESPONSE_STATUSES.has(response.status) && attempt < 2;
    if (!mayRetry) {
      throw new Error(payload?.detail ?? "자료를 불러오지 못했습니다.");
    }
    await waitForRetry(300 * 2 ** attempt, signal);
  }
  throw new Error("자료를 불러오지 못했습니다.");
}
