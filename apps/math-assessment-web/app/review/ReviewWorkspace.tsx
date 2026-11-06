"use client";

import Link from "../SiteLink";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { fetchCatalog, type CaseItem } from "../lib/catalog-api";
import {
  loadReviewState,
  MAX_REVIEW_CASES,
  queueCase,
  removeCase,
  REVIEW_DIMENSIONS,
  reviewRecord,
  reviewedDimensionCount,
  saveReviewState,
  storeReviewRecord,
  type ReviewDecision,
  type ReviewRating,
  type ReviewRecord,
  type ReviewState,
} from "./review-store";

const DECISION_LABELS: Record<ReviewDecision, string> = {
  pending: "판단 전",
  adopt: "설계 패턴으로 채택",
  hold: "추가 확인 후 보류",
  exclude: "이번 설계에서는 제외",
};

export default function ReviewWorkspace() {
  const searchParameters = useSearchParams();
  const requestedCase = searchParameters.get("case") || "";
  const [state, setState] = useState<ReviewState | null>(null);
  const [cases, setCases] = useState<Record<string, CaseItem>>({});
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<ReviewRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const queueKey = state?.queue.join(",") ?? "";
  const hydrated = state !== null;

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const loaded = loadReviewState(window.localStorage);
      const withRequested = requestedCase ? queueCase(loaded, requestedCase) : loaded;
      if (withRequested !== loaded) saveReviewState(window.localStorage, withRequested);
      const initialId = requestedCase && withRequested.queue.includes(requestedCase)
        ? requestedCase
        : (withRequested.queue[0] ?? "");
      setState(withRequested);
      setSelectedId(initialId);
      setDraft(initialId ? reviewRecord(withRequested, initialId) : null);
    });
    return () => { active = false; };
  }, [requestedCase]);

  useEffect(() => {
    if (!hydrated) return;
    const queuedCaseIds = queueKey ? queueKey.split(",") : [];
    const controller = new AbortController();
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      setLoading(queuedCaseIds.length > 0);
      setError("");
      if (!queuedCaseIds.length) setCases({});
    });
    if (!queuedCaseIds.length) return () => controller.abort();
    Promise.all(queuedCaseIds.map((caseId) => fetchCatalog<CaseItem>(`cases/${caseId}`, controller.signal)))
      .then((items) => setCases(Object.fromEntries(items.map((item) => [item.case_id, item]))))
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [hydrated, queueKey]);

  const selectedCase = selectedId ? cases[selectedId] : undefined;
  const reviewedCases = useMemo(
    () => state?.queue.filter((caseId) => state.decisions[caseId] && reviewedDimensionCount(state.decisions[caseId]) > 0).length ?? 0,
    [state],
  );

  function saveDraft() {
    if (!state || !draft) return;
    const next = storeReviewRecord(state, { ...draft, updatedAt: new Date().toISOString() });
    saveReviewState(window.localStorage, next);
    setState(next);
    setNotice("이 브라우저에 교사 검토를 저장했습니다.");
  }

  function removeSelected() {
    if (!state || !selectedId) return;
    const next = removeCase(state, selectedId);
    const nextId = next.queue[0] ?? "";
    saveReviewState(window.localStorage, next);
    setState(next);
    setSelectedId(nextId);
    setDraft(nextId ? reviewRecord(next, nextId) : null);
    setNotice("검토함에서 사례를 뺐습니다.");
  }

  function updateRating(id: (typeof REVIEW_DIMENSIONS)[number]["id"], rating: ReviewRating) {
    setDraft((current) => current ? { ...current, ratings: { ...current.ratings, [id]: rating } } : current);
    setNotice("");
  }

  return (
    <main id="main-content" className="reviewPage">
      <header className="pageHeaderCompact" aria-labelledby="review-title">
        <div>
          <p className="breadcrumb"><Link href="/">홈</Link><span>/</span>교사 검토함</p>
          <h1 id="review-title">교사 검토함</h1>
        </div>
        <p><strong>{state?.queue.length ?? 0}/{MAX_REVIEW_CASES}</strong><span>검토함 · 기록 {reviewedCases}건</span></p>
      </header>

      {!state || loading ? <div className="reviewLoading" role="status">검토할 사례를 불러오고 있습니다.</div> : null}
      {error ? <div className="reviewError" role="alert"><strong>검토함을 불러오지 못했습니다.</strong><p>{error}</p></div> : null}
      {state && !loading && !error && !state.queue.length ? (
        <section className="reviewEmpty">
          <span aria-hidden="true">＋</span><h2>검토함이 비어 있습니다</h2><p>사례 라이브러리에서 근거를 읽고 검토할 사례를 담아 주세요.</p><Link href="/cases">전체 사례에서 시작하기 →</Link>
        </section>
      ) : null}

      {state && !loading && !error && state.queue.length ? (
        <div className="reviewWorkspace">
          <aside className="reviewQueue" aria-labelledby="review-queue-title">
            <div><h2 id="review-queue-title">검토할 사례</h2><Link href="/cases">사례 더 담기</Link></div>
            <ol>{state.queue.map((caseId, index) => {
              const item = cases[caseId];
              const record = reviewRecord(state, caseId);
              return <li key={caseId}><button type="button" className={selectedId === caseId ? "selected" : ""} onClick={() => { setSelectedId(caseId); setDraft(reviewRecord(state, caseId)); setNotice(""); }}><span>{String(index + 1).padStart(2, "0")} · {item?.subject || "불러오는 중"}</span><strong>{item?.primary_task_name || caseId}</strong><small>{reviewedDimensionCount(record)}/6 기준 · {DECISION_LABELS[record.decision]}</small></button></li>;
            })}</ol>
          </aside>

          {selectedCase && draft ? (
            <section className="reviewCanvas" aria-labelledby="selected-review-title">
              <div className="reviewCaseHeader">
                <div><span>{selectedCase.curriculum} 개정 · {selectedCase.subject}</span><h2 id="selected-review-title">{selectedCase.primary_task_name}</h2><p>{selectedCase.school_name || "학교명 미확인"} · {selectedCase.region || "지역 미확인"}</p></div>
                <div><button type="button" onClick={removeSelected}>검토함에서 빼기</button>{selectedCase.source_url ? <a href={selectedCase.source_url} target="_blank" rel="noreferrer">학교알리미 원문 ↗</a> : null}</div>
              </div>
              <details className="reviewEvidence" open><summary>판단 근거 발췌</summary><p>{selectedCase.evidence_excerpt || "공개용 근거 발췌를 만들지 못했습니다."}</p></details>

              <fieldset className="reviewCriteria"><legend>여섯 기준으로 읽기 <small>각 항목은 교사가 직접 선택합니다.</small></legend>{REVIEW_DIMENSIONS.map((dimension) => <label key={dimension.id}><span><strong>{dimension.label}</strong><small>{dimension.prompt}</small></span><select value={draft.ratings[dimension.id]} onChange={(event) => updateRating(dimension.id, event.target.value as ReviewRating)}><option value="unreviewed">아직 보지 않음</option><option value="meets">충분함</option><option value="question">원문 확인 필요</option><option value="needs_work">재설계 시 보완</option></select></label>)}</fieldset>

              <fieldset className="reviewDecision"><legend>이번 설계에서의 판단</legend>{(Object.entries(DECISION_LABELS) as Array<[ReviewDecision, string]>).map(([value, label]) => <label key={value} className={draft.decision === value ? "selected" : ""}><input type="radio" name="decision" value={value} checked={draft.decision === value} onChange={() => setDraft({ ...draft, decision: value })} /><span>{label}</span></label>)}</fieldset>
              <label className="reviewNote"><span>판단 근거와 재설계 메모</span><textarea rows={5} maxLength={2000} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="예: 과정 증거는 좋지만, 모둠별 역할과 개인 기여 확인 기준을 추가한다." /></label>
              {notice ? <p className="reviewNotice" role="status">{notice}</p> : null}
              <div className="reviewActions"><button type="button" onClick={saveDraft}>교사 검토 저장</button><Link href={`/cases/${selectedCase.case_id}`}>원문 상세 확인 →</Link></div>
              <p className="reviewBoundary">검토 기록은 이 브라우저에만 저장됩니다. 자동 품질 점수나 모델 판단은 포함하지 않습니다.</p>
            </section>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}
