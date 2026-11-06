import type { Metadata } from "next";
import Link from "../SiteLink";

export const metadata: Metadata = {
  title: "사용설명서",
  description: "2026 수학 수행평가 아이디어 아카이브에서 유형별 참고, 전체 원문 라이브러리, 원문 비교와 교사 검토함을 구분해 사용하는 방법입니다.",
};

const workflow = [
  { number: "01", title: "유형별 설계 참고로 시작", description: "여섯 유형 안에서 원문 표 제목, 성취기준, 평가 방법·배점, 루브릭이 함께 확인된 사례를 우선순위대로 봅니다.", href: "/references", link: "유형별 설계 참고 열기" },
  { number: "02", title: "전체 라이브러리에서 조건 찾기", description: "교육과정, 수학 과목, 시·도, 시·군·구, 수행 방식과 검색어로 전체 사례를 좁힙니다. 이곳은 우수 사례만 모은 화면이 아닙니다.", href: "/cases", link: "전체 라이브러리 열기" },
  { number: "03", title: "원문 표와 루브릭 확인", description: "사례를 열어 수행평가 내용, 반영 비율, 성취기준, 평가 방법과 채점 기준을 웹앱 안의 원문 표에서 확인합니다.", href: "/cases", link: "수행평가 원문 보기" },
  { number: "04", title: "필요할 때만 비교·검토 사용", description: "원문 비교는 선택한 최대 네 항목의 원문 표를 나란히 읽는 도구입니다. 교사 검토함은 채택·수정·보류 판단과 메모를 이 브라우저에 저장하는 개인 작업 공간입니다.", href: "/compare", link: "원문 비교 열기" },
];

const statuses = [
  { label: "개별 수행평가 원문에서 정리", tone: "confirmed", description: "수행평가명과 해당 표·루브릭 구간이 분리되어 확인된 자료입니다.", action: "비교·설계 참고에 우선 사용" },
  { label: "여러 수행평가가 묶인 원문·경계 확인", tone: "review", description: "표 제목은 확인했지만 여러 평가 구간이 함께 있어 평가 항목 경계를 단정하지 않은 자료입니다.", action: "상세 원문에서 항목별 확인" },
  { label: "평가영역명 원문 확인 필요", tone: "review", description: "신뢰할 수 있는 수행평가명을 만들 수 없어, 감지된 원문 표현과 원문 표를 보여 주는 자료입니다.", action: "임의 제목으로 인용하지 않기" },
  { label: "과목 경계 불일치 · 비공개", tone: "blocked", description: "해당 수학 과목 원문임을 확인하지 못해 내용과 비교 기능을 공개하지 않은 자료입니다.", action: "학교알리미 원문에서 재확인" },
];

export default function GuidePage() {
  return <main id="main-content" className="catalogPage guidePage">
    <header className="pageHeaderCompact">
      <div><p className="breadcrumb"><Link href="/">홈</Link><span>/</span>사용설명서</p><h1>교사를 위한 사용설명서</h1></div>
      <p><strong>4단계</strong><span>찾기부터 교사 검토까지</span></p>
    </header>

    <section className="guideStart" aria-labelledby="guide-start-title">
      <div><p className="eyebrow">처음이라면</p><h2 id="guide-start-title">유형별 참고에서 고르고, 전체 라이브러리에서 확인하세요.</h2><p>이 서비스는 학교나 교사의 우열을 정하지 않습니다. 공개 평가계획의 원문 근거를 확인하고 우리 수업에 맞는 판단을 돕는 도구입니다.</p></div>
      <Link href="/references">유형별 참고 사례 보기 →</Link>
    </section>

    <section className="guideWorkflow" aria-labelledby="guide-workflow-title">
      <div className="sectionLabel"><span className="stepPill">이용 순서</span><div><h2 id="guide-workflow-title">두 라이브러리와 보조 도구의 역할</h2><p>찾기·원문 확인·개인 판단을 서로 섞지 않도록 나눴습니다.</p></div></div>
      <ol>{workflow.map((step) => <li key={step.number}><span>{step.number}</span><div><h3>{step.title}</h3><p>{step.description}</p><Link href={step.href}>{step.link} →</Link></div></li>)}</ol>
    </section>

    <section className="guideStatuses" aria-labelledby="guide-status-title">
      <div className="sectionLabel"><span className="stepPill">원문 상태</span><div><h2 id="guide-status-title">평가영역명은 확인 상태와 함께 보세요.</h2><p>원문 경계가 불명확할 때는 그럴듯한 이름을 새로 만들지 않습니다.</p></div></div>
      <div className="guideStatusTableWrap"><table><caption>수행평가명·원문 확인 상태와 권장 사용 방법</caption><thead><tr><th scope="col">화면 표시</th><th scope="col">뜻</th><th scope="col">권장 행동</th></tr></thead><tbody>{statuses.map((status) => <tr key={status.label}><th scope="row"><span className={`guideStatus ${status.tone}`}>{status.label}</span></th><td>{status.description}</td><td>{status.action}</td></tr>)}</tbody></table></div>
    </section>

    <section className="guideChecklist" aria-labelledby="guide-check-title">
      <div><p className="eyebrow">설계 전 점검</p><h2 id="guide-check-title">가져올 것은 형식이 아니라 평가 구조입니다.</h2></div>
      <ul><li><strong>성취기준</strong><span>과제와 채점 기준이 같은 수학 학습을 보고 있는가?</span></li><li><strong>수행 증거</strong><span>학생이 무엇을 만들고, 설명하고, 기록해야 하는가?</span></li><li><strong>수업 조건</strong><span>차시·학급·자료·도구 사용 방식이 우리 학교에서도 가능한가?</span></li><li><strong>루브릭</strong><span>과정과 결과의 질을 학생이 이해할 문장으로 구분했는가?</span></li></ul>
    </section>

    <section className="guideHelp" aria-labelledby="guide-help-title"><div><p className="eyebrow">자료 범위</p><h2 id="guide-help-title">원문과 해석의 경계를 확인하세요.</h2><p>미검출은 미개설을 뜻하지 않으며, 자동 탐지와 설계 참고 우선순위는 교사의 최종 판단을 대체하지 않습니다.</p></div><Link href="/sources">자료·해석 안내 보기 →</Link></section>
  </main>;
}
