"use client";

import Link from "../SiteLink";
import { useRouter, useSearchParams } from "next/navigation";
import { type CSSProperties, useEffect, useMemo, useState } from "react";

import {
  apiParameters,
  fetchCatalog,
  type SubjectItem,
  type SubjectListResponse,
  type TrendItem,
  type TrendListResponse,
} from "../lib/catalog-api";

const DEFAULT_CURRICULUM = "2022";
const DEFAULT_SUBJECT = "대수";

function safeCurriculum(value: string | null) {
  return value === "2015" || value === "2022" ? value : DEFAULT_CURRICULUM;
}

function percentage(value: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((value / total) * 100)}%`;
}

function displayYears(values: number[]) {
  return values.length ? values.join("·") : "연도 미확인";
}

export default function TrendsExplorer() {
  const searchParameters = useSearchParams();
  const router = useRouter();
  const initialCurriculum = safeCurriculum(searchParameters.get("curriculum"));
  const initialSubject = searchParameters.get("subject") || DEFAULT_SUBJECT;
  const [subjects, setSubjects] = useState<SubjectItem[]>([]);
  const [curriculum, setCurriculum] = useState(initialCurriculum);
  const [subject, setSubject] = useState(initialSubject);
  const [trend, setTrend] = useState<TrendItem | null>(null);
  const [caution, setCaution] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<SubjectListResponse>("subjects", controller.signal)
      .then((payload) => setSubjects(payload.items.filter((item) => item.curriculum !== "shared")))
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const parameters = apiParameters({ curriculum, subject });
    fetchCatalog<TrendListResponse>(`trends?${parameters}`, controller.signal)
      .then((payload) => {
        setTrend(payload.items[0] ?? null);
        setCaution(payload.caution);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [curriculum, subject]);

  useEffect(() => {
    const parameters = apiParameters({ curriculum, subject });
    router.replace(`/trends?${parameters}`, { scroll: false });
  }, [curriculum, subject, router]);

  const courseOptions = useMemo(
    () => subjects.filter((item) => item.curriculum === curriculum),
    [curriculum, subjects],
  );

  function changeCurriculum(value: string) {
    const nextCourses = subjects.filter((item) => item.curriculum === value);
    setLoading(true);
    setError("");
    setCurriculum(value);
    setSubject(nextCourses.some((item) => item.subject === subject) ? subject : (nextCourses[0]?.subject ?? ""));
  }

  function changeSubject(value: string) {
    setLoading(true);
    setError("");
    setSubject(value);
  }

  function resetCourse() {
    setLoading(true);
    setError("");
    setCurriculum(DEFAULT_CURRICULUM);
    setSubject(DEFAULT_SUBJECT);
  }

  const maximumTagCount = Math.max(...(trend?.action_tags.map((item) => item.documents) ?? [1]));
  const caseLink = `/cases?${apiParameters({ curriculum, subject })}`;

  return (
    <main id="main-content" className="catalogPage">
      <header className="pageHeaderCompact" aria-labelledby="trends-title">
        <div>
          <p className="breadcrumb"><Link href="/">홈</Link><span>/</span>공개자료 경향</p>
          <h1 id="trends-title">과목별 수행평가 경향</h1>
        </div>
        <p><strong>8,800</strong><span>수집 정규화 사례</span></p>
      </header>

      <section className="filterDock" aria-labelledby="course-filter-title">
        <div className="filterDockHeading">
          <div>
            <span className="stepPill">1</span>
            <h2 id="course-filter-title">살펴볼 과목</h2>
          </div>
          <button type="button" onClick={resetCourse}>
            초기화
          </button>
        </div>
        <div className="filterControls">
          <label>
            <span>교육과정</span>
            <select value={curriculum} onChange={(event) => changeCurriculum(event.target.value)}>
              <option value="2015">2015 개정</option>
              <option value="2022">2022 개정</option>
            </select>
          </label>
          <label className="wideControl">
            <span>수학 과목</span>
            <select value={subject} onChange={(event) => changeSubject(event.target.value)}>
              {courseOptions.map((item) => (
                <option key={`${item.curriculum}-${item.subject}`} value={item.subject}>
                  {item.subject} · {item.documents.toLocaleString()}건
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="activeFilters" aria-label="현재 선택">
          <span>현재 선택</span>
          <strong>{curriculum} 개정</strong>
          <strong>{subject}</strong>
        </div>
      </section>

      {loading ? <LoadingTrends /> : null}
      {error ? <ErrorPanel message={error} /> : null}
      {!loading && !error && !trend ? <EmptyPanel /> : null}

      {!loading && !error && trend ? (
        <>
          {trend.small_sample ? (
            <div className="sampleWarning" role="status">
              <strong>표본이 {trend.documents}건입니다.</strong>
              <span>이 과목의 결과를 전국적인 일반 경향으로 확대해 해석하지 마세요.</span>
            </div>
          ) : null}

          <section className="metricSection" aria-labelledby="overview-title">
            <div className="sectionLabel">
              <span className="stepPill">2</span>
              <div><h2 id="overview-title">한눈에 보는 {subject}</h2><p>{displayYears(trend.academic_years)}학년도 평가계획 기준</p></div>
            </div>
            <dl className="catalogMetrics">
              <div><dt>확인 문서</dt><dd>{trend.documents.toLocaleString()}<small>건</small></dd></div>
              <div><dt>확인 학교</dt><dd>{trend.schools.toLocaleString()}<small>곳</small></dd></div>
              <div><dt>루브릭 근거</dt><dd>{percentage(trend.evidence_documents.rubric, trend.documents)}</dd></div>
              <div><dt>성취기준 근거</dt><dd>{percentage(trend.evidence_documents.achievement_standard, trend.documents)}</dd></div>
            </dl>
          </section>

          <div className="insightGrid">
            <section className="insightCard" aria-labelledby="activity-title">
              <div className="cardHeading">
                <div><p className="eyebrow">활동 표지</p><h2 id="activity-title">많이 확인된 수행 방식</h2></div>
                <span>문서 기준</span>
              </div>
              <ol className="barList">
                {trend.action_tags.slice(0, 8).map((item) => (
                  <li key={item.tag}>
                    <div><strong>{item.tag}</strong><span>{item.documents.toLocaleString()}건 · {item.schools.toLocaleString()}개교</span></div>
                    <div className="barTrack" aria-hidden="true"><span style={{ "--bar-size": `${(item.documents / maximumTagCount) * 100}%` } as CSSProperties} /></div>
                  </li>
                ))}
              </ol>
              <p className="cardCaution">자동 탐지 표지이며, 의미 기반 과제 유형은 교사 검토 뒤 확정합니다.</p>
            </section>

            <section className="insightCard" aria-labelledby="evidence-title">
              <div className="cardHeading">
                <div><p className="eyebrow">설계 근거</p><h2 id="evidence-title">평가계획의 근거 충실도</h2></div>
                <span>포함 문서</span>
              </div>
              <dl className="evidenceMeters">
                {[
                  ["루브릭·채점기준", trend.evidence_documents.rubric],
                  ["성취기준", trend.evidence_documents.achievement_standard],
                  ["배점·반영비율", trend.evidence_documents.weight_or_points],
                  ["평가방법", trend.evidence_documents.assessment_method],
                ].map(([label, value]) => (
                  <div key={String(label)}>
                    <dt><span>{label}</span><strong>{Number(value).toLocaleString()}건</strong></dt>
                    <dd><span style={{ "--meter-size": percentage(Number(value), trend.documents) } as CSSProperties} /></dd>
                  </div>
                ))}
              </dl>
              <p className="scoreNote">증거 완결성 중앙값 <strong>{trend.median_evidence_score ?? "-"}</strong> · 설계 품질 점수가 아닙니다.</p>
            </section>
          </div>

          <section className="coverageSection" aria-labelledby="coverage-title">
            <div className="sectionLabel">
              <span className="stepPill">3</span>
              <div><h2 id="coverage-title">학교별 확인 상태</h2><p>공개계획 확인 대상 2,407개 학교 × 교육과정 × 과목 확인표 기준</p></div>
            </div>
            <div className="coverageGrid">
              <div className="coveragePrimary"><span>평가계획에서 발견</span><strong>{(trend.coverage.found ?? 0).toLocaleString()}</strong><small>학교</small></div>
              <dl>
                <div><dt>교육과정 판별 유보</dt><dd>{(trend.coverage.found_curriculum_ambiguous ?? 0).toLocaleString()}</dd></div>
                <div><dt>평가계획에서 미검출</dt><dd>{(trend.coverage.not_found_in_collected_plans ?? 0).toLocaleString()}</dd></div>
                <div><dt>개설 여부 미확인</dt><dd>{(trend.coverage.offering_unknown ?? 0).toLocaleString()}</dd></div>
                <div><dt>추출 실패</dt><dd>{(trend.coverage.extraction_failed ?? 0).toLocaleString()}</dd></div>
              </dl>
            </div>
            <div className="interpretationNote"><strong>해석 주의</strong><p>{caution}</p></div>
          </section>

          <section className="nextActionCard">
            <div><p className="eyebrow">다음 단계</p><h2>숫자 뒤에 있는 실제 사례를 살펴보세요</h2><p>{curriculum} 개정 {subject} 사례에서 과제명, 활동 표지, 평가 근거를 비교합니다.</p></div>
            <Link href={caseLink}>{subject} 사례 보기 <span aria-hidden="true">→</span></Link>
          </section>
        </>
      ) : null}
    </main>
  );
}

function LoadingTrends() {
  return <div className="loadingPanel" role="status"><span /><div><strong>경향 자료를 불러오는 중입니다</strong><p>문서와 학교 수를 확인하고 있습니다.</p></div></div>;
}

function ErrorPanel({ message }: { message: string }) {
  return <div className="errorPanel" role="alert"><strong>자료를 불러오지 못했습니다.</strong><p>{message}</p></div>;
}

function EmptyPanel() {
  return <div className="emptyPanel"><strong>이 조건에서 확인된 자료가 없습니다.</strong><p>다른 교육과정이나 과목을 선택해 보세요.</p></div>;
}
