"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import MathText from "../MathText";
import Link from "../SiteLink";
import { apiParameters, fetchCatalog, type DesignReferenceResponse, type DesignTag } from "../lib/catalog-api";

const PAGE_SIZE = 12;
const TOPICS: Record<string, string> = {
  limits: "극한과 연속", derivatives: "미분", integrals: "적분",
};
const METHODS: Record<string, string> = {
  reasoning: "추론·증명", graphing: "그래프·시각화", "problem-writing": "문항제작",
  modeling: "수학적 모델링", "data-analysis": "자료분석", calculation: "계산·연산",
  "problem-solving": "문제해결", writing: "서술·논술", discussion: "발표·토론",
  inquiry: "탐구", process: "과정평가",
};
const ARTIFACTS: Record<string, string> = {
  report: "보고서", presentation: "발표자료", portfolio: "활동지·포트폴리오", product: "제작물",
};
const TAG_LABELS = { topic: TOPICS, method: METHODS, artifact: ARTIFACTS };
const AXIS_LABELS = { topic: "주제", method: "방법", artifact: "산출물" };
const FIELDS = { title: "원문 평가명", overview: "평가 개요", method: "원문 평가 방법", standard: "성취기준" };

function knownOption(value: string | null, options: Record<string, string>) {
  return value && Object.hasOwn(options, value) ? value : "";
}

function TagEvidence({ tags }: { tags: DesignTag[] }) {
  const topicLabels = tags.filter((tag) => tag.axis === "topic").map((tag) => TOPICS[tag.tag]);
  const methodLabels = tags.filter((tag) => tag.axis === "method").map((tag) => METHODS[tag.tag]);
  return (
    <div className="designEvidence">
      <p><span>{topicLabels.join(" · ") || "주제 미분류"}</span><span aria-hidden="true">×</span><span>{methodLabels.join(" · ") || "방법 미분류"}</span></p>
      {tags.length ? <details><summary>분류 근거</summary><dl>{tags.map((tag) => (
        <div key={`${tag.axis}-${tag.tag}`}><dt>{AXIS_LABELS[tag.axis]} · {TAG_LABELS[tag.axis][tag.tag]}</dt><dd>{FIELDS[tag.source_field]} <q>{tag.evidence}</q></dd></div>
      ))}</dl></details> : null}
    </div>
  );
}

export default function DesignExplorer() {
  const query = useSearchParams();
  const [topic, setTopic] = useState(() => knownOption(query.get("topic"), TOPICS));
  const [method, setMethod] = useState(() => knownOption(query.get("method"), METHODS));
  const [page, setPage] = useState(() => Math.max(1, Math.min(150, Number.parseInt(query.get("page") || "1", 10) || 1)));
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string; response?: DesignReferenceResponse; error?: string }>();
  const [facets, setFacets] = useState<Pick<DesignReferenceResponse, "topics" | "methods">>();
  const offset = (page - 1) * PAGE_SIZE;
  const request = apiParameters({ topic, method, limit: PAGE_SIZE, offset });
  const key = `${request}/${revision}`;

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<DesignReferenceResponse>(`design-references?${request}`, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setState({ key, response });
        setFacets({ topics: response.topics, methods: response.methods });
      })
      .catch((error: Error) => { if (!controller.signal.aborted) setState({ key, error: error.message }); });
    return () => controller.abort();
  }, [key, request]);

  useEffect(() => {
    const search = apiParameters({ topic, method, page: page > 1 ? page : undefined });
    const url = search ? `/references?${search}` : "/references";
    if (window.location.pathname + window.location.search !== url) window.history.replaceState(null, "", url);
  }, [topic, method, page]);

  const active = state?.key === key ? state : undefined;
  const result = active?.response;
  const pageCount = Math.max(1, Math.ceil((result?.total || 0) / PAGE_SIZE));
  const listTitle = topic || method ? `${TOPICS[topic] || "전체 주제"} × ${METHODS[method] || "전체 방법"}` : "미적분Ⅰ 수행평가";

  return (
    <main className="catalogPage designExplorer" id="main-content">
      <header className="designExplorerHeader">
        <p className="breadcrumb"><Link href="/">홈</Link><span>/</span>유형별 설계 참고</p>
        <h1>같은 수학 주제, 다른 수행평가</h1>
        <p>2학기 미적분Ⅰ에서 무엇을 평가했고, 학생이 어떻게 수행했는지 찾아보세요.</p>
        <nav aria-label="설계 참고 범위">
          <Link href="/standards">같은 성취기준으로 과제 비교</Link>
          <Link href="/references?view=categories">전 과목 설계 유형</Link>
          <Link href="/cases?semester=2">2학기 전체 라이브러리</Link>
        </nav>
      </header>

      <section className="designControls" aria-labelledby="design-controls-title">
        <h2 id="design-controls-title">주제와 방법 고르기</h2>
        <div className="designAxes">
          <fieldset>
            <legend>주제 <small>무엇을 평가하나요?</small></legend>
            <div className="designTopicOptions">
              {Object.entries({ "": "전체", ...TOPICS }).map(([value, label]) => (
                <label key={value}>
                  <input type="radio" name="design-topic" value={value} checked={topic === value}
                    onChange={() => { setTopic(value); setPage(1); }} />
                  <span>{label}{value && facets ? <small>{(facets.topics[value] || 0).toLocaleString()}</small> : null}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="designMethodControl">
            <span>방법 <small>학생이 무엇을 하나요?</small></span>
            <select value={method} onChange={(event) => { setMethod(event.target.value); setPage(1); }}>
              <option value="">전체 방법</option>
              {Object.entries(METHODS).map(([value, label]) => (
                <option value={value} key={value}>{label}{facets ? ` (${(facets.methods[value] || 0).toLocaleString()}개)` : ""}</option>
              ))}
            </select>
          </label>
        </div>
        <p className="designSourceNote">평가명, 개요, 성취기준 등에서 확인한 표현으로 분류했습니다. 한 평가가 여러 주제나 방법에 해당할 수 있습니다. <a href="https://ipsi.dongguk.edu/admission/html/counsel/noticeView.asp?BOARD_IDX=36946" target="_blank" rel="noreferrer">동국대 가이드북 참고</a></p>
      </section>

      <section className="designResults" aria-labelledby="design-results-title" aria-busy={!active}>
        <header className="designResultHeader">
          <div><h2 id="design-results-title">{listTitle}</h2><p aria-live="polite">{result?.available ? `${result.total.toLocaleString()}개 수행평가 · 2학기 미적분Ⅰ ${result.indexed_items.toLocaleString()}개 중` : "2학기 미적분Ⅰ"}</p></div>
          {(topic || method) ? <button type="button" onClick={() => { setTopic(""); setMethod(""); setPage(1); }}>조건 초기화</button> : null}
        </header>
        {!active ? <p className="compactLoading" role="status">수행평가를 찾고 있습니다.</p> : null}
        {active?.error ? <div className="errorPanel" role="alert"><p>사례를 불러오지 못했습니다.</p><button type="button" onClick={() => setRevision(revision + 1)}>다시 불러오기</button></div> : null}
        {result && !result.available ? <p className="compactEmpty">이 데이터에는 2학기 미적분Ⅰ 분류가 없습니다. <Link href="/references?view=categories">전 과목 설계 유형 보기</Link></p> : null}
        {result?.available && !result.items.length ? <p className="compactEmpty">이 조건에서 볼 수 있는 수행평가가 없습니다. 주제나 방법을 다시 골라 보세요.</p> : null}
        {result?.items.length ? (
          <ul className="designResultsList">{result.items.map((item) => (
            <li key={item.item_id}>
              <div className="designResultIdentity">
                <h3><Link href={`/cases/${item.case_id}?item=${item.item_id}`}><MathText text={item.title} /></Link></h3>
                <p>{item.school_name} · {item.region}</p>
              </div>
              <TagEvidence tags={item.tags} />
              <p className="designRubricState" data-confirmed={item.has_rubric}>{item.has_rubric ? "채점표 확인" : "별도 채점표 미확인"}</p>
            </li>
          ))}</ul>
        ) : null}
        {result?.available && (pageCount > 1 || page > 1) ? <nav className="pagination" aria-label="수행평가 결과 페이지">
          <button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>이전</button>
          <span>{page} / {pageCount}</span>
          <button type="button" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>다음</button>
        </nav> : null}
        <p className="designSourceNote">원문에 평가명, 성취기준, 배점, 채점표 등이 함께 확인되는 순서입니다. 과제의 품질을 판단하려면 원문과 수업 조건을 함께 보세요.</p>
      </section>
    </main>
  );
}
