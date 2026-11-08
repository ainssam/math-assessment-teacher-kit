"use client";

import Link from "../SiteLink";
import MathText from "../MathText";
import { useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  apiParameters,
  fetchCatalog,
  type CaseItem,
  type CaseListResponse,
  type FacetResponse,
  type SubjectItem,
  type SubjectListResponse,
} from "../lib/catalog-api";
import { loadReviewState, queueCase, saveReviewState } from "../review/review-store";
import CasePeriod, { CURRENT_ACADEMIC_YEAR } from "./CasePeriod";

const PAGE_SIZE = 20;
const SEMESTER_OPTIONS = [
  ["", "전체 자료"],
  ["1", `${CURRENT_ACADEMIC_YEAR}학년도 1학기`],
  ["2", `${CURRENT_ACADEMIC_YEAR}학년도 2학기`],
  ["unknown", "학년도·학기 미확인"],
] as const;

function safeCurriculum(value: string | null) {
  return value === "2015" || value === "2022" || value === "shared" ? value : "";
}

function safeOffset(value: string | null) {
  const page = Number.parseInt(value || "1", 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page - 1, 999) * PAGE_SIZE : 0;
}

function uniqueSubjectOptions(subjects: SubjectItem[], curriculum: string) {
  const totals = new Map<string, number>();
  for (const item of subjects) {
    if (curriculum && item.curriculum !== curriculum) continue;
    totals.set(item.subject, (totals.get(item.subject) ?? 0) + item.documents);
  }
  return [...totals.entries()].map(([subject, documents]) => ({ subject, documents }));
}

export default function CasesExplorer() {
  const searchParameters = useSearchParams();
  const initialCurriculum = safeCurriculum(searchParameters.get("curriculum"));
  const initialSubject = searchParameters.get("subject") || "";
  const initialQuery = searchParameters.get("q") || "";
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [curriculum, setCurriculum] = useState(initialCurriculum);
  const [subject, setSubject] = useState(initialSubject);
  const [semester, setSemester] = useState(() => {
    const value = searchParameters.get("semester");
    return value === "1" || value === "2" || value === "unknown" ? value : "";
  });
  const academicYear = semester === "1" || semester === "2" ? CURRENT_ACADEMIC_YEAR : undefined;
  const [region, setRegion] = useState(searchParameters.get("region") || "");
  const [district, setDistrict] = useState(searchParameters.get("district") || "");
  const [tag, setTag] = useState(searchParameters.get("tag") || "");
  const [queryInput, setQueryInput] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const [offset, setOffset] = useState(safeOffset(searchParameters.get("page")));
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<FacetResponse>({ regions: [], districts: [], action_tags: [] });
  const [caution, setCaution] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [subjectNotice, setSubjectNotice] = useState("");
  const [facetNotice, setFacetNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<SubjectListResponse>("subjects", controller.signal)
      .then((payload) => {
        setSubjects(payload.items);
        setSubjectNotice("");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setSubjectNotice("과목 목록을 불러오지 못했습니다. 사례 검색은 계속 사용할 수 있습니다.");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const parameters = apiParameters({ curriculum, subject, region, semester, academic_year: academicYear });
    fetchCatalog<FacetResponse>(`facets?${parameters}`, controller.signal)
      .then((payload) => {
        setFacets(payload);
        setFacetNotice("");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setFacetNotice("지역·수행 방식 목록을 불러오지 못했습니다. 검색 결과는 계속 확인할 수 있습니다.");
        }
      });
    return () => controller.abort();
  }, [curriculum, subject, region, semester, academicYear]);

  useEffect(() => {
    const controller = new AbortController();
    const parameters = apiParameters({
      curriculum,
      subject,
      region,
      district,
      tag,
      semester,
      academic_year: academicYear,
      query,
      include_ambiguous: true,
      limit: PAGE_SIZE,
      offset,
    });
    fetchCatalog<CaseListResponse>(`cases?${parameters}`, controller.signal)
      .then((payload) => {
        setCases(payload.items);
        setTotal(payload.total);
        setCaution(payload.caution);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [curriculum, subject, region, district, tag, semester, academicYear, query, offset]);

  useEffect(() => {
    const parameters = apiParameters({
      curriculum, subject, region, district, tag, semester, q: query,
      page: offset ? Math.floor(offset / PAGE_SIZE) + 1 : undefined,
    });
    const url = parameters ? `/cases?${parameters}` : "/cases";
    if (window.location.pathname + window.location.search !== url) window.history.replaceState(null, "", url);
  }, [curriculum, subject, region, district, tag, semester, query, offset]);

  const courseOptions = useMemo(
    () => uniqueSubjectOptions(subjects, curriculum),
    [curriculum, subjects],
  );
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const activeFilterCount = [curriculum, subject, semester, region, district, tag, query].filter(Boolean).length;

  function beginReload() {
    setLoading(true);
    setError("");
  }

  function changeCurriculum(value: string) {
    const nextCourses = uniqueSubjectOptions(subjects, value);
    beginReload();
    setCurriculum(value);
    setSubject(nextCourses.some((item) => item.subject === subject) ? subject : "");
    setRegion("");
    setDistrict("");
    setTag("");
    setOffset(0);
  }

  function changeSubject(value: string) {
    beginReload();
    setSubject(value);
    setRegion("");
    setDistrict("");
    setTag("");
    setOffset(0);
  }

  function clearFilters() {
    if (activeFilterCount || offset) beginReload();
    setCurriculum("");
    setSubject("");
    setSemester("");
    setRegion("");
    setDistrict("");
    setTag("");
    setQueryInput("");
    setQuery("");
    setOffset(0);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    beginReload();
    setQuery(queryInput.trim());
    setOffset(0);
  }

  return (
    <main id="main-content" className="catalogPage caseCatalogPage">
      <header className="pageHeaderCompact">
        <div>
          <p className="breadcrumb"><Link href="/">홈</Link><span>/</span>전체 라이브러리</p>
          <h1 id="cases-title">전체 수행평가 라이브러리</h1>
        </div>
        <p><strong>{total.toLocaleString()}</strong><span>현재 조건의 사례</span></p>
      </header>

      <section className="caseFilterPanel" aria-labelledby="case-filter-title">
        <div className="caseFilterTopline"><h2 id="case-filter-title">사례 찾기</h2><button type="button" onClick={clearFilters}>전체로 초기화{activeFilterCount ? ` (${activeFilterCount})` : ""}</button></div>
        <fieldset className="semesterFilter">
          <legend>학년도·학기</legend>
          <div className="semesterChoices designTopicOptions">
            {SEMESTER_OPTIONS.map(([value, label]) => (
              <label key={value}>
                <input type="radio" name="case-semester" value={value} checked={semester === value}
                  onChange={() => { beginReload(); setSemester(value); setOffset(0); }} />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="filterControls caseCourseControls">
          <label><span>교육과정</span><select value={curriculum} onChange={(event) => changeCurriculum(event.target.value)}><option value="">전체 교육과정</option><option value="2015">2015 개정</option><option value="2022">2022 개정</option><option value="shared">교육과정 확인 필요</option></select></label>
          <label className="wideControl"><span>수학 과목</span><select value={subject} onChange={(event) => changeSubject(event.target.value)}><option value="">전체 수학 과목</option>{courseOptions.map((item) => <option key={item.subject} value={item.subject}>{item.subject}</option>)}</select></label>
          <label><span>시·도</span><select value={region} onChange={(event) => { beginReload(); setRegion(event.target.value); setDistrict(""); setOffset(0); }}><option value="">전국</option>{region && !facets.regions.some((item) => item.value === region) ? <option value={region}>{region}</option> : null}{facets.regions.map((item) => <option key={item.value} value={item.value}>{item.value} · {item.count}</option>)}</select></label>
          <label><span>시·군·구</span><select value={district} onChange={(event) => { beginReload(); setDistrict(event.target.value); setOffset(0); }} disabled={!region}><option value="">{region ? "전체 시·군·구" : "시·도를 먼저 선택"}</option>{district && !facets.districts.some((item) => item.value === district) ? <option value={district}>{district}</option> : null}{region ? facets.districts.map((item) => <option key={item.value} value={item.value}>{item.value} · {item.count}</option>) : null}</select></label>
        </div>
        <form className="caseSearch" onSubmit={submitSearch} role="search">
          <label htmlFor="case-query">수행평가명·평가 개요·학교 검색</label>
          <div><input id="case-query" value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder="예: 미적분, 탐구보고서, 모델링, 독서" /><button type="submit">검색</button></div>
        </form>
        <fieldset className="tagFilters">
          <legend>수행 방식</legend>
          <button type="button" className={!tag ? "selected" : ""} onClick={() => { beginReload(); setTag(""); setOffset(0); }}>전체</button>
          {facets.action_tags.slice(0, 9).map((item) => <button type="button" className={tag === item.value ? "selected" : ""} aria-pressed={tag === item.value} key={item.value} onClick={() => { beginReload(); setTag(item.value === tag ? "" : item.value); setOffset(0); }}>{item.value}<span>{item.count}</span></button>)}
        </fieldset>
        <div className="activeFilters caseActiveFilters" aria-label="적용된 필터"><span>적용</span><strong>{curriculum === "shared" ? "교육과정 확인 필요" : curriculum ? `${curriculum} 개정` : "전체 교육과정"}</strong><strong>{subject || "전체 수학 과목"}</strong><strong>원문 경계 확인 자료만</strong>{region ? <button type="button" onClick={() => { beginReload(); setRegion(""); setDistrict(""); setOffset(0); }}>{region} ×</button> : null}{district ? <button type="button" onClick={() => { beginReload(); setDistrict(""); setOffset(0); }}>{district} ×</button> : null}{tag ? <button type="button" onClick={() => { beginReload(); setTag(""); setOffset(0); }}>{tag} ×</button> : null}{query ? <button type="button" onClick={() => { beginReload(); setQuery(""); setQueryInput(""); setOffset(0); }}>{query} ×</button> : null}</div>
        {subjectNotice || facetNotice ? <p className="filterNotice" role="status">{[subjectNotice, facetNotice].filter(Boolean).join(" ")}</p> : null}
      </section>

      <section className="librarySplitNotice" aria-label="라이브러리 이용 안내">
        <div><strong>미적분Ⅰ에서 같은 주제의 다른 방법을 찾고 있나요?</strong><span>2026학년도 2학기 사례를 주제와 방법으로 함께 골라 볼 수 있습니다.</span></div>
        <Link href="/references">미적분Ⅰ 주제 × 방법 보기</Link>
      </section>

      <section className="caseResults" aria-labelledby="case-results-title" aria-busy={loading}>
        <div className="resultHeading"><div><span className="stepPill">결과</span><div><h2 id="case-results-title">평가 구조 표</h2><p>{total.toLocaleString()}건 중 {total ? offset + 1 : 0}–{Math.min(offset + PAGE_SIZE, total)}건</p></div></div><Link href={`/trends?${apiParameters({ curriculum, subject })}`}>전체 자료의 과목별 경향 보기</Link></div>
        {loading ? <CaseSkeletons /> : null}
        {error ? <div className="errorPanel" role="alert"><strong>자료를 불러오지 못했습니다.</strong><p>{error}</p></div> : null}
        {!loading && !error && cases.length === 0 ? <div className="emptyPanel"><strong>조건에 맞는 사례가 없습니다.</strong><p>검색어 또는 필터를 조정해 보세요.</p></div> : null}
        {!loading && !error && cases.length ? <div className="tableScroll caseTableScroll"><table className="caseTable"><thead><tr><th>수행평가명·학교</th><th>평가 구조</th><th>근거</th><th>사용</th></tr></thead><tbody>{cases.map((item) => <CaseTableRow key={item.case_id} item={item} />)}</tbody></table></div> : null}
        {!loading && !error && totalPages > 1 ? <nav className="pagination" aria-label="사례 목록 페이지"><button type="button" disabled={offset === 0} onClick={() => { beginReload(); setOffset(Math.max(0, offset - PAGE_SIZE)); }}>← 이전</button><span><strong>{currentPage}</strong> / {totalPages}</span><button type="button" disabled={offset + PAGE_SIZE >= total} onClick={() => { beginReload(); setOffset(offset + PAGE_SIZE); }}>다음 →</button></nav> : null}
        {caution ? <p className="caseCaution"><strong>해석 안내</strong>{caution}</p> : null}
      </section>
    </main>
  );
}

function structureRows(item: CaseItem) {
  const structure = item.assessment_structure;
  return [
    ["평가 개요", structure.overview],
    ["평가 방법", structure.methods.join(" · ")],
    ["배점·반영", structure.weight],
    ["성취기준", structure.standards.join(", ")],
    ["평가 요소", structure.criteria.join(" · ")],
  ].filter((row) => row[1]);
}

function hasSourceGroundedTaskTitle(item: CaseItem) {
  return item.primary_task_name !== "구체적 과제명 미탐지" && !item.primary_task_name.includes("수행평가 원문 구간");
}

function hasBundleBoundaryWarning(item: CaseItem) {
  return item.assessment_structure.basis === "source_detail_bundle_review";
}

function confirmedTaskNames(item: CaseItem) {
  if (!hasSourceGroundedTaskTitle(item)) return [];
  return Array.from(new Set([item.primary_task_name, ...item.task_names]))
    .filter((value) => value && value !== "구체적 과제명 미탐지");
}

export function CaseTableRow({ item }: { item: CaseItem }) {
  const [reviewNotice, setReviewNotice] = useState("");
  const rows = structureRows(item);
  const titleWasDetected = hasSourceGroundedTaskTitle(item);
  const bundleBoundaryWarning = hasBundleBoundaryWarning(item);
  const taskNames = confirmedTaskNames(item);

  function addToReview() {
    const current = loadReviewState(window.localStorage);
    const next = queueCase(current, item.case_id);
    saveReviewState(window.localStorage, next);
    setReviewNotice(next === current ? "이미 검토함에 있습니다." : "검토함에 담았습니다.");
  }

  return <tr>
    <td data-label="수행평가명·학교" className="caseIdentityCell">
      <div className="caseBadges"><span>{item.curriculum === "shared" ? "교육과정 확인 필요" : `${item.curriculum} 개정`}</span><span>{item.subject}</span><CasePeriod years={item.academic_years} semesters={item.semesters} /></div>
      {taskNames.length > 1 ? (
        <div className="confirmedTaskList">
          <span>확인된 수행평가 {taskNames.length}개</span>
          <ol>{taskNames.map((value) => <li key={value}><Link href={`/cases/${item.case_id}`}><MathText text={value} /></Link></li>)}</ol>
        </div>
      ) : <strong><Link href={`/cases/${item.case_id}`}><MathText text={titleWasDetected ? item.primary_task_name : "평가영역명 원문 확인 필요"} /></Link></strong>}
      {!titleWasDetected ? <small>근거 없는 이름을 만들지 않고, 여러 평가가 섞인 원문 묶음으로 남겨 두었습니다.</small> : null}
      {titleWasDetected && bundleBoundaryWarning ? <small>원문에서 표 제목은 확인했지만 여러 평가 구간이 함께 있어, 상세에서 항목별 원문을 확인해 주세요.</small> : null}
      {!titleWasDetected && item.task_names.length ? <div className="sourceAreaList" aria-label="원문에서 확인된 평가영역명 또는 표현"><span>원문 평가영역·표현</span>{item.task_names.slice(0, 3).map((value) => <em key={value}><MathText text={value} /></em>)}</div> : null}
      <p>{item.school_name || "학교명 미확정"}{item.region ? ` · ${item.region}` : ""}{item.district ? ` ${item.district}` : ""}</p>
    </td>
    <td data-label="평가 구조" className="caseStructureCell">
      {rows.length ? <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><MathText text={value} /></dd></div>)}</dl> : <p><MathText text={item.evidence_excerpt || "정리할 수 있는 구조 항목이 없습니다."} /></p>}
      <small className="basisLabel">{item.assessment_structure.basis === "source_detail" ? "개별 수행평가 원문에서 정리" : item.assessment_structure.basis === "source_detail_bundle_review" ? "여러 수행평가가 묶인 원문·경계 확인" : item.assessment_structure.basis === "table" ? "원문 표 항목에서 정리" : item.assessment_structure.basis === "heading" ? "원문 제목 구조에서 정리" : item.assessment_structure.basis === "section" ? "수행평가 구간에서 정리" : item.assessment_structure.basis === "area" ? "원문 평가영역만 확인" : item.assessment_structure.basis === "missing" ? "과제명·구조 미확정" : "원문 문맥에서 자동 정리"}</small>
    </td>
    <td data-label="근거" className="caseEvidenceCell"><EvidenceMarkers item={item} />{item.priority_signals.length ? <div className="signalChips">{item.priority_signals.slice(0, 4).map((signal) => <span key={signal}>{signal}</span>)}</div> : null}</td>
    <td data-label="사용" className="caseUseCell"><Link className="caseSourceLink" href={`/cases/${item.case_id}`}>수행평가 원문·표 보기 →</Link><button type="button" onClick={addToReview}>검토함에 담기</button>{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">학교알리미 원문 ↗</a> : <span>공개 페이지 미확정</span>}{reviewNotice ? <small role="status">{reviewNotice}</small> : null}</td>
  </tr>;
}

function EvidenceMarkers({ item }: { item: CaseItem }) {
  const markers = [["rubric", "채점기준"], ["achievement_standard", "성취기준"], ["weight_or_points", "배점"], ["assessment_method", "평가방법"]] as const;
  const count = markers.filter(([key]) => item.evidence_markers[key] > 0).length;
  return <div className="evidenceMarkerCompact" title="원문에서 확인된 근거 항목 수"><strong>{count}<span>/4</span></strong><ul>{markers.map(([key, label]) => <li className={item.evidence_markers[key] > 0 ? "confirmed" : ""} key={key}>{item.evidence_markers[key] > 0 ? "●" : "○"} {label}</li>)}</ul></div>;
}

export function CaseCard({ item }: { item: CaseItem }) {
  const excerptPreview = item.evidence_excerpt.slice(0, 320);
  const hasMoreExcerpt = item.evidence_excerpt.length > excerptPreview.length;
  const titleWasDetected = hasSourceGroundedTaskTitle(item);
  const markerCount = Object.values(item.evidence_markers).filter((value) => value > 0).length;
  return <article className="caseCard">
    <div className="caseCardTopline"><div className="caseBadges"><span>{item.curriculum === "shared" ? "교육과정 확인 필요" : `${item.curriculum} 개정`}</span><span>{item.subject}</span><CasePeriod years={item.academic_years} semesters={item.semesters} /></div><div className="evidenceScore" title="원문에서 확인된 항목 수"><small>근거 항목</small><strong>{markerCount}<span>/4</span></strong></div></div>
    <div className="caseTitle"><span>{titleWasDetected ? "원문 표·제목에서 확인한 수행평가명" : "원문 확인 대상"}</span><h3>{titleWasDetected ? item.primary_task_name : "평가영역명 원문 확인 필요"}</h3>{!titleWasDetected ? <p>근거 없는 이름을 만들지 않고 원문 확인 대상으로 남겨 두었습니다.</p> : null}</div>
    <p className="caseCardLocation">{item.school_name} · {item.region}{item.district ? ` ${item.district}` : ""}</p>
    <section className="evidenceExcerpt"><strong>정리한 발췌</strong><p>{excerptPreview}</p>{hasMoreExcerpt ? <details className="evidenceDetails"><summary>전체 발췌 보기</summary><p>{item.evidence_excerpt}</p></details> : null}</section>
    {item.task_names.length > (titleWasDetected ? 1 : 0) ? <details className="candidateDetails"><summary>{titleWasDetected ? `함께 감지한 과제명 후보 ${item.task_names.length}개` : `원문 평가영역·표현 ${item.task_names.length}개`}</summary><ul>{item.task_names.map((value) => <li key={value}>{value}</li>)}</ul></details> : null}
  </article>;
}

function CaseSkeletons() {
  return <div className="caseSkeletons" role="status" aria-label="사례를 불러오는 중">{Array.from({ length: 3 }, (_, index) => <div key={index}><span /><span /><span /></div>)}</div>;
}
