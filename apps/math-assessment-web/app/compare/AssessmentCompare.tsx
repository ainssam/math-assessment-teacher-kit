"use client";

import Link from "../SiteLink";
import MathText from "../MathText";
import SourceDocumentHtml from "../SourceDocumentHtml";
import { useEffect, useState } from "react";

import {
  type AssessmentItemDetail,
  type StandardReferenceResponse,
  apiParameters,
  fetchCatalog,
} from "../lib/catalog-api";
import {
  loadCompareItems,
  saveCompareItems,
} from "../lib/compare-store";
import { hasStandardCode, MATH_COURSES, type MathCurriculum } from "../lib/math-standards";

const COMPARISON_ROWS: Array<[string, (item: AssessmentItemDetail) => string]> = [
  ["학교·지역", (item) => `${item.school_name}${item.region ? ` · ${item.region}` : ""}`],
  ["교육과정·과목", (item) => `${item.curriculum === "shared" ? "교육과정 확인 필요" : `${item.curriculum} 개정`} · ${item.subject}`],
  ["수행평가명", (item) => item.title_raw],
  ["평가 개요", (item) => item.overview.replace(/<br\s*\/?>/gi, "\n")],
  ["평가 방법", (item) => item.method.replace(/<br\s*\/?>/gi, "\n")],
  ["시기", (item) => item.timing],
  ["만점", (item) => item.score],
  ["반영·배점", (item) => item.weight],
  ["성취기준", (item) => item.standards.join(", ")],
  ["채점 기준", (item) => item.has_rubric ? "원문 채점표 있음" : "별도 채점표 미탐지"],
];

export default function AssessmentCompare({ requestedIds, standard = "", subject = "", curriculum = "2022" }: {
  requestedIds?: string[]; standard?: string; subject?: string; curriculum?: MathCurriculum;
}) {
  const [items, setItems] = useState<AssessmentItemDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reference, setReference] = useState<StandardReferenceResponse>();

  useEffect(() => {
    const ids = requestedIds ?? loadCompareItems(window.localStorage);
    const controller = new AbortController();
    Promise.allSettled(ids.map((id) => fetchCatalog<AssessmentItemDetail>(`assessment-items/${id}`, controller.signal)))
      .then((results) => {
        if (controller.signal.aborted) return;
        const nextItems = results
          .filter((result): result is PromiseFulfilledResult<AssessmentItemDetail> => result.status === "fulfilled")
          .map((result) => result.value);
        const readableItems = nextItems.filter((item) => item.source_available !== false);
        setItems(readableItems);
        if (readableItems.length !== ids.length) {
          setError("일부 항목은 공개 경계 확인 또는 불러오기 실패로 비교에서 제외했습니다.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [requestedIds]);

  useEffect(() => {
    if (!standard || !MATH_COURSES[curriculum].includes(subject)) return;
    const controller = new AbortController();
    fetchCatalog<StandardReferenceResponse>(`standard-references?${apiParameters({ curriculum, subject, standard, limit: 1 })}`, controller.signal)
      .then((response) => { if (!controller.signal.aborted) setReference(response); })
      .catch(() => { /* The original assessment tables remain readable. */ });
    return () => controller.abort();
  }, [curriculum, standard, subject]);

  const sharedStandard = reference?.curriculum === curriculum && reference.subject === subject && reference.standard?.key === standard && items.length >= 2 && items.every((item) =>
    item.curriculum === curriculum && item.subject === subject && hasStandardCode(item.standards, standard),
  ) ? reference.standard : null;

  function removeItem(itemId: string) {
    const next = items.filter((item) => item.item_id !== itemId);
    setItems(next);
    if (requestedIds) {
      const params = new URLSearchParams({ items: next.map((item) => item.item_id).join(","), standard, curriculum, subject });
      window.history.replaceState(null, "", `/compare?${params}`);
    } else saveCompareItems(window.localStorage, next.map((item) => item.item_id));
  }

  return (
    <main id="main-content" className="comparisonPage">
      <header className="pageHeaderCompact">
        <div><p className="breadcrumb"><Link href={standard ? `/standards?${apiParameters({ curriculum, subject, standard })}` : "/cases"}>{standard ? "성취기준으로 찾기" : "수행평가 라이브러리"}</Link><span>/</span>비교함</p><h1>{sharedStandard ? "같은 성취기준의 두 과제 비교" : "수행평가 원문 비교"}</h1></div>
        <p><strong>{items.length}</strong><span>선택한 수행평가</span></p>
      </header>
      {loading ? <p className="routeLoading">비교할 원문을 불러오고 있습니다.</p> : null}
      {error ? <div className="errorPanel" role="alert"><strong>비교 자료를 불러오지 못했습니다.</strong><p>{error}</p></div> : null}
      {sharedStandard ? <section className="standardStatement" aria-label="두 과제의 공통 성취기준"><strong>{sharedStandard.code}</strong><MathText text={sharedStandard.text} /><p>두 학교의 평가계획에 이 성취기준 코드가 함께 적혀 있습니다.</p><a href={reference!.source_url} target="_blank" rel="noreferrer">교육과정 원문</a></section> : null}
      {standard && !loading && items.length >= 2 && reference && !sharedStandard ? <p role="status">선택한 성취기준을 두 과제 모두에서 확인할 수 없습니다. 각 과제의 원문 성취기준을 확인해 주세요.</p> : null}
      {!loading && !items.length ? <div className="emptyPanel"><strong>비교함이 비어 있습니다.</strong><p>사례 상세에서 수행평가를 최대 4개까지 담아 주세요.</p><Link href="/cases">사례 찾기 →</Link></div> : null}
      {items.length ? (
        <>
          <div className="comparisonTableScroll">
            <table className="comparisonTable">
              <thead><tr><th>비교 항목</th>{items.map((item) => <th key={item.item_id}><strong>{item.title}</strong><button type="button" onClick={() => removeItem(item.item_id)}>빼기</button></th>)}</tr></thead>
              <tbody>{COMPARISON_ROWS.map(([label, read]) => <tr key={label}><th>{label}</th>{items.map((item) => { const value = read(item); return <td key={item.item_id}>{value ? <MathText text={value} /> : <span className="emptyValue">원문 값 미탐지</span>}</td>; })}</tr>)}</tbody>
            </table>
          </div>
          <section className="comparisonSources" aria-labelledby="comparison-source-title">
            <div className="sectionTopline"><div><span className="stepPill">원문</span><h2 id="comparison-source-title">채점표와 수행 내용 나란히 보기</h2></div></div>
            {sharedStandard ? <p className="comparisonReadGuide">학생이 무엇을 설명하거나 제출하는지, 그 수행을 어느 채점 항목에서 평가하는지 나란히 살펴보세요.</p> : null}
            <div>{items.map((item) => <article key={item.item_id}><header><span>{item.region}</span><h3>{item.title}</h3><p>{item.school_name} · {item.subject}</p><a href={item.source_url} target="_blank" rel="noreferrer">학교알리미 원문</a></header>
              {item.source_notes?.length ? <aside className="sourceTrustNotice" aria-label="원문 확인 메모"><strong>원문 확인 메모</strong>{item.source_notes.map((note) => <p key={note}>{note}</p>)}</aside> : null}
              {sharedStandard ? <>
                <section className="comparisonEvidence"><h4>수행 내용 · 원문 평가 개요</h4>{item.overview ? <MathText text={item.overview.replace(/<br\s*\/?>/gi, "\n")} /> : <p>아래 수행평가 원문에서 학생의 수행 내용을 확인하세요.</p>}<h4>평가 방법</h4>{item.method ? <MathText text={item.method.replace(/<br\s*\/?>/gi, "\n")} /> : <p>원문 표에서 확인</p>}</section>
                <section className="comparisonRubric"><h4>채점기준 원문</h4>{item.rubric_html ? <SourceDocumentHtml html={item.rubric_html} previews={item.rubric_previews} coveredTableKeys={item.rubric_preview_table_keys} coveredExcerpt={item.rubric_excerpt_covered} /> : <p>이 과제에서 별도 채점표를 확인하지 못했습니다.</p>}</section>
                <details className="comparisonFullSource"><summary>수행평가 원문 전체 펼치기</summary><SourceDocumentHtml html={item.source_html} previews={item.source_previews} coveredTableKeys={item.source_preview_table_keys} coveredExcerpt={item.source_excerpt_covered} /></details>
              </> : <SourceDocumentHtml html={item.source_html} previews={item.source_previews} coveredTableKeys={item.source_preview_table_keys} coveredExcerpt={item.source_excerpt_covered} />}
            </article>)}</div>
          </section>
        </>
      ) : null}
    </main>
  );
}
