"use client";

import Link from "../../SiteLink";
import MathText from "../../MathText";
import CasePeriod from "../CasePeriod";
import SourceDocumentHtml from "../../SourceDocumentHtml";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  type AssessmentItemDetail,
  type AssessmentItemSummary,
  type CaseDetailResponse,
  type CaseItem,
  fetchCatalog,
} from "../../lib/catalog-api";
import {
  loadCompareItems,
  MAX_COMPARE_ITEMS,
  toggleCompareItem,
} from "../../lib/compare-store";

export default function CaseDetailViewer({
  caseId,
  initialItemId,
}: {
  caseId: string;
  initialItemId?: string;
}) {
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null);
  const [detail, setDetail] = useState<CaseDetailResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [loadedItems, setLoadedItems] = useState<Record<string, AssessmentItemDetail>>({});
  const requestedItems = useRef(new Set<string>());
  const [compareItems, setCompareItems] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchCatalog<CaseItem>(`cases/${caseId}`, controller.signal),
      fetchCatalog<CaseDetailResponse>(`cases/${caseId}/detail`, controller.signal),
    ])
      .then(([nextCase, nextDetail]) => {
        setCaseItem(nextCase);
        setDetail(nextDetail);
        const firstReadable = nextDetail.items.find((candidate) => candidate.source_available !== false);
        setSelectedId(
          nextDetail.items.some((item) => item.item_id === initialItemId)
            ? initialItemId || ""
            : firstReadable?.item_id || nextDetail.items[0]?.item_id || "",
        );
        setCompareItems(loadCompareItems(window.localStorage));
        setError("");
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setError(reason.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [caseId, initialItemId]);

  useEffect(() => {
    if (!selectedId || loadedItems[selectedId] || requestedItems.current.has(selectedId)) return;
    const controller = new AbortController();
    requestedItems.current.add(selectedId);
    fetchCatalog<AssessmentItemDetail>(`assessment-items/${selectedId}`, controller.signal)
      .then((item) => setLoadedItems((current) => ({ ...current, [selectedId]: item })))
      .catch((reason: Error) => {
        requestedItems.current.delete(selectedId);
        if (reason.name !== "AbortError") setError(reason.message);
      });
    return () => controller.abort();
  }, [loadedItems, selectedId]);

  const selectedSummary = useMemo(
    () => detail?.items.find((item) => item.item_id === selectedId) || null,
    [detail, selectedId],
  );
  const selectedItem = selectedId ? loadedItems[selectedId] : null;

  function toggleComparison(item: AssessmentItemSummary) {
    const next = toggleCompareItem(window.localStorage, item.item_id);
    setCompareItems(next);
  }

  if (loading) {
    return <main id="main-content" className="sourceDetailPage"><p className="routeLoading">원문 표를 불러오고 있습니다.</p></main>;
  }
  if (error || !caseItem || !detail) {
    return (
      <main id="main-content" className="sourceDetailPage">
        <div className="errorPanel" role="alert"><strong>수행평가 원문을 열지 못했습니다.</strong><p>{error || "상세 데이터가 없습니다."}</p></div>
        <Link href="/cases">← 라이브러리로 돌아가기</Link>
      </main>
    );
  }

  return (
    <main id="main-content" className="sourceDetailPage">
      <header className="sourceDetailHeader">
        <div>
          <p className="breadcrumb"><Link href="/cases">수행평가 라이브러리</Link><span>/</span>원문 상세</p>
          <div className="caseBadges"><span>{caseItem.curriculum === "shared" ? "교육과정 유보" : `${caseItem.curriculum} 개정`}</span><span>{caseItem.subject}</span><CasePeriod years={caseItem.academic_years} semesters={caseItem.semesters} /><span>{caseItem.region || "지역 미확인"}</span></div>
          <h1>{caseItem.school_name}</h1>
          <p>{caseItem.source_name}</p>
        </div>
        <div className="sourceDetailActions">
          <button type="button" onClick={() => window.print()}>PDF로 저장·인쇄</button>
          <a href={caseItem.source_url} target="_blank" rel="noreferrer">학교알리미 공개 페이지 ↗</a>
        </div>
      </header>

      <section className="sourceTrustNotice" aria-label="원문 표시 원칙">
        <strong>{selectedItem?.source_previews?.length ? "원문 그림과 추출 표를 함께 제공합니다." : "원문 텍스트와 표 구조를 안전 변환한 재현본입니다."}</strong>
        <p>{selectedItem?.source_previews?.length ? "수식과 병합 모양은 원문 그림에서 확인하고, 텍스트는 ‘추출 표 함께 보기’에서 읽을 수 있습니다. 원문 페이지 전체를 보여 주는 경우에는 같은 페이지의 다른 평가나 안내가 함께 보일 수 있습니다." : "표의 문구와 구조를 보존하려 했지만 지면 배치·도형·병합 셀 모양은 달라질 수 있습니다. 최종 인용 전 학교알리미 원문과 대조하고, 항목 경계가 확실하지 않은 문서는 ‘재검토 묶음’ 표시를 확인해 주세요."}</p>
        <span className={detail.extraction_status === "bounded" ? "confirmed" : "review"}>{detail.extraction_status === "bounded" ? "개별 수행평가 경계 확인" : "원문 구간 묶음 · 경계 재검토"}</span>
      </section>

      {detail.extraction_status !== "bounded" && detail.detected_titles.length ? (
        <section className="detectedTitleNotice" aria-label="원문 표에서 확인한 수행평가명">
          <strong>원문 표에서 확인한 수행평가명</strong>
          <ul>{detail.detected_titles.map((title) => <li key={title}>{title}</li>)}</ul>
          <p>평가명은 확인했지만 각 루브릭과의 경계를 확정하지 못해 원문은 하나의 묶음으로 표시합니다.</p>
        </section>
      ) : null}

      <div className="sourceDetailLayout">
        <aside className="assessmentItemNav" aria-label="문서 안 수행평가">
          <div><strong>원문 구간 {detail.items.length}개</strong><span>문서 등장 순서</span></div>
          {detail.items.map((item) => (
            <div className={selectedId === item.item_id ? "selected" : ""} key={item.item_id}>
              <button type="button" onClick={() => setSelectedId(item.item_id)}><span>{item.order}</span><strong>{item.title}</strong><small>{item.extraction_status === "bounded" ? "개별 구간" : item.source_available !== false ? "재검토 묶음" : "과목 경계 불일치 · 비공개"}</small></button>
              <label><input type="checkbox" checked={compareItems.includes(item.item_id)} onChange={() => toggleComparison(item)} disabled={item.source_available === false || (!compareItems.includes(item.item_id) && compareItems.length >= MAX_COMPARE_ITEMS)} /> 비교함</label>
            </div>
          ))}
          <Link className="compareBasketLink" href="/compare">비교함 보기 <strong>{compareItems.length}</strong></Link>
        </aside>

        <article className="assessmentSourcePaper">
          {selectedItem?.source_notes?.length ? <section className="sourceTrustNotice" aria-label="원문 확인 메모"><strong>원문 확인 메모</strong>{selectedItem.source_notes.map((note) => <p key={note}>{note}</p>)}</section> : null}
          {selectedSummary ? <SourceFacts item={selectedItem || selectedSummary} detectedTitles={detail.detected_titles} /> : null}
          {!selectedItem ? <p className="compactLoading">선택한 원문 표를 불러오고 있습니다.</p> : null}
          {selectedItem ? (
            <>
              <div className="sourcePaperTopline"><div><span>{selectedItem.source_previews?.length ? "원문 표" : "원문 추출 표"}</span><h2>{selectedItem.title === "수행평가 원문 구간" && detail.detected_titles.length === 1 ? detail.detected_titles[0] : selectedItem.title === "수행평가 원문 구간" && detail.detected_titles.length > 1 ? `수행평가명 ${detail.detected_titles.length}개 확인 · 원문 묶음` : selectedItem.title}</h2></div><small>{selectedItem.title_basis === "heading" ? "원문 제목에서 분리" : selectedItem.title_basis === "table" ? "원문 표의 평가명" : "평가명 확인 · 원문 경계 묶음"}</small></div>
              {selectedItem.source_available === false ? (
                <div className="sourceMismatchNotice" role="status"><strong>이 구간은 공개 전 추가 확인이 필요합니다.</strong><p>{selectedItem.extraction_status === "source_mismatch_review" ? "수학 과목 원문 경계를 확인하지 못해 내용을 숨겼습니다." : "여러 평가 구간이 묶여 있어 항목 경계와 개인정보 안전 검토를 마칠 때까지 표 재현본을 공개하지 않습니다."} 학교알리미 원문에서 확인해 주세요.</p></div>
              ) : <SourceDocumentHtml html={selectedItem.source_html} previews={selectedItem.source_previews} coveredTableKeys={selectedItem.source_preview_table_keys} coveredExcerpt={selectedItem.source_excerpt_covered} />}
              {selectedItem.source_available !== false && selectedItem.rubric_html ? (
                <section className="sourceRubric" aria-labelledby="source-rubric-title">
                  <header>
                    <div><span>채점 기준 원문</span><h3 id="source-rubric-title">루브릭·평가기준 원문 다시 보기</h3></div>
                    <p>채점기준이 확인된 원문 구간을 다시 표시합니다. 같은 페이지의 평가 개요와 안내가 함께 보일 수 있습니다.</p>
                  </header>
                  <SourceDocumentHtml html={selectedItem.rubric_html} previews={selectedItem.rubric_previews} coveredTableKeys={selectedItem.rubric_preview_table_keys} coveredExcerpt={selectedItem.rubric_excerpt_covered} />
                </section>
              ) : null}
            </>
          ) : null}
        </article>
      </div>
    </main>
  );
}

function SourceFacts({ item, detectedTitles }: { item: AssessmentItemSummary; detectedTitles: string[] }) {
  if (item.source_available === false) {
    return <section className="sourceFacts" aria-label="원문 확인 상태"><h2>원문 확인 상태</h2><p>{item.extraction_status === "source_mismatch_review" ? "수학 과목 경계를 확인하지 못해 추출값을 공개하지 않습니다." : "여러 평가 구간이 묶여 있어 항목 경계와 개인정보 안전 검토를 마칠 때까지 표 재현본을 공개하지 않습니다."}</p></section>;
  }
  const confirmedBundleTitles = item.title === "수행평가 원문 구간" ? detectedTitles : [];
  const rows = [
    [confirmedBundleTitles.length ? "원문 표의 평가명" : "평가명", confirmedBundleTitles.length ? confirmedBundleTitles.join(" · ") : item.title_raw],
    ["평가 개요", item.overview],
    ["평가 방법", item.method],
    ["시기", item.timing],
    ["만점", item.score],
    ["반영·배점", item.weight],
    ["성취기준", item.standards.join(", ")],
    ["채점 기준", item.has_rubric ? "원문 표 있음" : "별도 표 미탐지"],
  ].filter(([, value]) => value);
  return (
    <section className="sourceFacts" aria-label="원문에서 읽은 평가 항목">
      <h2>항목별 원문 값</h2>
      <div className="sourceFactsTableWrap">
        <table>
          <caption>원문에서 그대로 추출한 수행평가명, 내용, 방법, 시기, 배점과 성취기준</caption>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}><th scope="row">{label}</th><td><MathText text={value} /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
