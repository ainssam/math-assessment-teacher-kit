import type { Metadata } from "next";
import Link from "../SiteLink";

import OfficialSources from "./OfficialSources";
import PublicationSnapshot from "./PublicationSnapshot";

export const metadata: Metadata = {
  title: "자료와 해석 안내",
  description: "수학 수행평가 사례의 출처, 처리 과정과 해석 범위를 설명합니다.",
};

const stages = [
  ["01", "원문 보존", "학교알리미에 공개된 평가계획 원문은 수정하지 않고 별도 보존합니다."],
  ["02", "본문 추출", "한글·PDF 등 첨부파일의 본문을 읽고 추출 상태와 원문 해시를 남깁니다."],
  ["03", "수학 근거 탐지", "과목명, 성취기준 코드, 수행평가·루브릭 표지를 규칙 기반으로 확인합니다."],
  ["04", "원문 구간 제공", "과목별 수행평가 구간을 표 구조로 보여 주고, 경계가 불확실하면 묶음 상태를 함께 표시합니다."],
];

export default function SourcesPage() {
  return (
    <main id="main-content" className="catalogPage sourcesPage">
      <header className="pageHeaderCompact">
        <div><p className="breadcrumb"><Link href="/">홈</Link><span>/</span>자료 안내</p><h1>자료와 해석 안내</h1></div>
        <p><strong>4단계</strong><span>출처·처리·공개 경계 확인</span></p>
      </header>

      <PublicationSnapshot />

      <section className="sourceProcess" aria-labelledby="process-title">
        <div className="sectionLabel"><span className="stepPill">1</span><div><h2 id="process-title">자료가 화면에 오기까지</h2><p>원문과 서비스 데이터를 분리합니다.</p></div></div>
        <ol>{stages.map(([number, title, description]) => <li key={number}><span>{number}</span><div><h3>{title}</h3><p>{description}</p></div></li>)}</ol>
      </section>

      <section className="interpretationRules" aria-labelledby="rules-title">
        <div className="sectionLabel"><span className="stepPill">2</span><div><h2 id="rules-title">반드시 지키는 해석 원칙</h2><p>자동 분류 결과를 학교 평가로 사용하지 않습니다.</p></div></div>
        <div>
          <article><strong>미검출 ≠ 미개설</strong><p>수집한 평가계획에서 과목을 발견하지 못했을 뿐, 실제 학교 개설 여부를 단정할 수 없습니다.</p></article>
          <article><strong>증거 점수 ≠ 설계 품질</strong><p>루브릭·성취기준 등 필요한 근거가 얼마나 확인되는지를 나타내며 우수성 순위가 아닙니다.</p></article>
          <article><strong>활동 표지 ≠ 최종 유형</strong><p>‘탐구’, ‘보고서’ 같은 단어를 규칙으로 찾은 결과입니다. 의미 기반 분류에는 교사 검토가 필요합니다.</p></article>
          <article><strong>2025년 자료는 별도</strong><p>2015 개정 수학Ⅱ의 전국 경향은 2025학년도 역사 자료를 추가 수집한 뒤 확정합니다.</p></article>
        </div>
      </section>

      <OfficialSources />

      <section className="privacyBoundary">
        <div><p className="eyebrow">공개 경계</p><h2>검토를 통과한 수행평가 표 구간을 확인합니다</h2><p>사례 상세에는 학교알리미 공개 평가계획 중 과목 경계와 항목 경계를 확인한 표·루브릭의 안전 변환본만 표시합니다. 전체 첨부파일은 재배포하지 않으며, 경계가 불확실하거나 개인정보 검토가 필요한 묶음은 메타데이터와 공개 학교알리미 링크만 제공합니다. 지면 배치·도형이 중요하면 반드시 공식 원문과 대조하세요.</p></div>
        <Link href="/trends">검증된 경향 보기 →</Link>
      </section>
    </main>
  );
}
