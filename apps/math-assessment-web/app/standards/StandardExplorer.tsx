"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import Link from "../SiteLink";
import MathText from "../MathText";
import CasePeriod from "../cases/CasePeriod";
import { apiParameters, fetchCatalog, type StandardReferenceItem, type StandardReferenceResponse } from "../lib/catalog-api";
import { MATH_COURSES, type MathCurriculum } from "../lib/math-standards";

const PAGE_SIZE = 12;

export default function StandardExplorer() {
  const search = useSearchParams();
  const [curriculum, setCurriculum] = useState<MathCurriculum>(() => search.get("curriculum") === "2015" ? "2015" : "2022");
  const [subject, setSubject] = useState(() => MATH_COURSES[curriculum].includes(search.get("subject") || "") ? search.get("subject")! : curriculum === "2022" ? "미적분Ⅰ" : "수학");
  const [standard, setStandard] = useState(search.get("standard") || "");
  const [semester, setSemester] = useState(() => ["1", "2"].includes(search.get("semester") || "") ? search.get("semester")! : "");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string; response?: StandardReferenceResponse; error?: string }>();
  const [selection, setSelection] = useState<StandardReferenceItem[]>([]);
  const request = apiParameters({ curriculum, subject, standard, semester, limit: PAGE_SIZE, offset });
  const key = `${request}/${revision}`;
  const active = state?.key === key ? state : undefined;
  const result = active?.response;
  const options = state?.response?.subject === subject && state.response.curriculum === curriculum ? state.response.standards : [];

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<StandardReferenceResponse>(`standard-references?${request}`, controller.signal)
      .then((response) => { if (!controller.signal.aborted) setState({ key, response }); })
      .catch((error: Error) => { if (!controller.signal.aborted) setState({ key, error: error.message }); });
    return () => controller.abort();
  }, [key, request]);

  useEffect(() => {
    const params = apiParameters({ curriculum, subject, standard, semester });
    window.history.replaceState(null, "", `/standards?${params}`);
  }, [curriculum, subject, standard, semester]);

  function resetResults() { setOffset(0); setSelection([]); }
  function select(item: StandardReferenceItem) {
    setSelection((current) => current.some((chosen) => chosen.item_id === item.item_id)
      ? current.filter((chosen) => chosen.item_id !== item.item_id) : [...current, item].slice(0, 2));
  }
  const compareUrl = `/compare?${apiParameters({ items: selection.map((item) => item.item_id).join(","), standard: result?.standard?.key, curriculum, subject })}`;

  return <main id="main-content" className="catalogPage standardExplorer">
    <header className="designExplorerHeader">
      <p className="breadcrumb"><Link href="/references">유형별 설계 참고</Link><span>/</span>성취기준 비교</p>
      <h1>같은 성취기준, 다른 과제</h1>
      <p>성취기준을 고르고 두 과제의 수행 내용과 채점표를 비교해 보세요.</p>
    </header>
    <section className="standardControls" aria-label="성취기준 선택">
      <div className="standardSelects">
        <label><span>교육과정</span><select value={curriculum} onChange={(e) => {
          const next = e.target.value as MathCurriculum;
          setCurriculum(next);
          if (!MATH_COURSES[next].includes(subject)) setSubject(MATH_COURSES[next][0]);
          setStandard(""); resetResults();
        }}><option value="2022">2022 개정</option><option value="2015">2015 개정</option></select></label>
        <label><span>수학 과목</span><select value={subject} onChange={(e) => { setSubject(e.target.value); setStandard(""); resetResults(); }}>{MATH_COURSES[curriculum].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>2026학년도 학기</span><select value={semester} onChange={(e) => { setSemester(e.target.value); resetResults(); }}><option value="">전체 학기</option><option value="1">1학기</option><option value="2">2학기</option></select></label>
        <label className="standardCodeSelect"><span>성취기준</span><select value={standard || result?.standard?.key || ""} disabled={!options.length} onChange={(e) => { setStandard(e.target.value); resetResults(); }}>
          {!options.length ? <option value="">불러오는 중</option> : null}
          {standard && !options.some((entry) => entry.key === standard) ? <option value={standard}>성취기준을 다시 선택해 주세요</option> : null}
          {options.map((entry) => <option value={entry.key} key={entry.key}>{entry.code} {entry.text} ({entry.count}개)</option>)}
        </select></label>
      </div>
      {result?.standard ? <div className="standardStatement"><strong>{result.standard.code}</strong><MathText text={result.standard.text} /><a href={result.source_url} target="_blank" rel="noreferrer">교육과정 원문</a></div> : null}
      <p className="designSourceNote">선택한 교육과정·과목의 학교 원문에 이 코드가 적힌 수행평가입니다. 교육과정이 불명확한 자료는 이 목록에 포함하지 않습니다. 여러 성취기준이 함께 적힌 과제는 실제 수행 내용과 채점표를 함께 살펴보세요.</p>
    </section>

    <section className="standardSelection" aria-label="비교할 두 과제" aria-live="polite">
      <div><strong>비교할 과제 {selection.length}/2</strong>{selection.length ? <ul>{selection.map((item) => <li key={item.item_id}><span>{item.school_name} · {item.title}</span><button type="button" onClick={() => select(item)} aria-label={`${item.title} 선택 해제`}>빼기</button></li>)}</ul> : <p>목록에서 두 과제를 선택하세요.</p>}</div>
      {selection.length === 2 && result ? <Link className="primaryAction" href={compareUrl}>두 과제 비교하기</Link> : <button type="button" className="primaryAction" disabled>두 과제 비교하기</button>}
    </section>

    <section className="designResults" aria-labelledby="standard-results" aria-busy={!active}>
      <header className="designResultHeader"><h2 id="standard-results">성취기준이 같은 수행평가</h2><p>{result ? `${result.total.toLocaleString()}개` : "확인 중"}</p></header>
      {!active ? <p role="status" className="compactLoading">사례를 찾고 있습니다.</p> : null}
      {active?.error ? <div className="errorPanel" role="alert"><p>사례를 불러오지 못했습니다.</p><button type="button" onClick={() => setRevision(revision + 1)}>다시 불러오기</button></div> : null}
      {result && !result.items.length ? <p className="compactEmpty">이 조건에서 성취기준 코드가 확인된 과제가 없습니다. 과목 미개설을 뜻하지 않습니다. 다른 성취기준이나 학기를 골라 보세요.</p> : null}
      <ul className="standardResults">{result?.items.map((item) => {
        const checked = selection.some((chosen) => chosen.item_id === item.item_id);
        return <li key={item.item_id}>
          <div className="standardResultMain"><div className="caseBadges"><CasePeriod years={item.academic_years} semesters={item.semesters} /><span>{item.has_rubric ? "채점표 확인" : "별도 채점표 미확인"}</span></div><h3><Link href={`/cases/${item.case_id}?item=${item.item_id}`}><MathText text={item.title} /></Link></h3><p>{item.school_name} · {item.region}</p>
            <dl><div><dt>수행 내용</dt><dd>{item.overview ? <MathText text={item.overview.replace(/<br\s*\/?>/gi, "\n")} /> : "원문 표에서 확인"}</dd></div><div><dt>평가 방법</dt><dd>{item.method ? <MathText text={item.method.replace(/<br\s*\/?>/gi, "\n")} /> : "원문 표에서 확인"}</dd></div></dl>
          </div>
          <label className="standardPick"><input type="checkbox" checked={checked} disabled={!checked && selection.length === 2} onChange={() => select(item)} /><span>{checked ? "선택됨" : "비교 선택"}<span className="srOnly"> · {item.school_name} {item.title}</span></span></label>
        </li>;
      })}</ul>
      {result && result.total > PAGE_SIZE ? <nav className="pagination" aria-label="성취기준 사례 페이지"><button disabled={!offset} onClick={() => setOffset(offset - PAGE_SIZE)}>이전</button><span>{offset / PAGE_SIZE + 1} / {Math.ceil(result.total / PAGE_SIZE)}</span><button disabled={offset + PAGE_SIZE >= result.total} onClick={() => setOffset(offset + PAGE_SIZE)}>다음</button></nav> : null}
    </section>
  </main>;
}
