import Link from "./SiteLink";

const metrics = [
  { value: "1,537", label: "공개 확정 학교" },
  { value: "10,760", label: "공개 수행평가" },
  { value: "4,863", label: "공개 확정 사례" },
];

const workflow = [
  {
    number: "01",
    title: "실제 경향을 살펴봅니다",
    description: "교육과정과 과목을 골라 수집된 공개 평가계획의 수행 유형, 산출물, 평가 요소를 확인합니다.",
    href: "/trends",
    action: "경향 탐색",
  },
  {
    number: "02",
    title: "근거 사례를 비교합니다",
    description: "출처가 확인되는 사례에서 재사용할 설계 요소와 수업 조건을 비교합니다.",
    href: "/cases",
    action: "사례 보기",
  },
];

export default function Home() {
  return (
    <main id="main-content">
      <section className="hero" aria-labelledby="hero-title">
        <div className="heroCopy">
          <p className="eyebrow">2026학년도 교수·학습 및 평가계획 기반</p>
          <h1 id="hero-title">다른 학교 수행평가에서<br />수업 아이디어를 찾습니다</h1>
          <p className="heroDescription">
            수행평가명, 활동 내용, 반영 비율, 성취기준과 채점기준을 원문 근거로 찾아보고 비교합니다.
            그대로 베끼는 목록이 아니라 우리 수업에 맞는 아이디어를 찾는 출발점입니다.
          </p>
          <div className="heroActions">
            <Link className="primaryAction" href="/cases">다른 학교 사례 찾아보기</Link>
            <Link className="secondaryAction" href="/references">유형별 아이디어 보기</Link>
          </div>
          <p className="pilotNote"><span aria-hidden="true">●</span> 2015·2022 개정 수학 과목의 수행평가 사례를 탐색합니다.</p>
        </div>

        <aside className="evidencePanel" aria-label="현재 데이터 기준선">
          <div className="panelTopline">
            <span>검증된 데이터 기준선</span>
            <strong>2026.08</strong>
          </div>
          <dl className="metricList">
            {metrics.map((metric) => (
              <div key={metric.label}>
                <dt>{metric.label}</dt>
                <dd>{metric.value}</dd>
              </div>
            ))}
          </dl>
          <p>2026년 8월 원문·과목 경계·개인정보 검토를 통과한 공개 자료 기준입니다. 전국 학교 전수나 과목 개설 현황을 뜻하지 않습니다.</p>
        </aside>
      </section>

      <section className="workflowSection" aria-labelledby="workflow-title">
        <div className="sectionHeading">
          <div>
            <p className="eyebrow">교사의 설계 흐름</p>
            <h2 id="workflow-title">찾고, 비교합니다</h2>
          </div>
          <p>자동으로 정답을 고르는 대신 근거와 판단 기준을 함께 보여 줍니다.</p>
        </div>
        <ol className="workflowGrid">
          {workflow.map((item) => (
            <li key={item.number}>
              <span className="stepNumber">{item.number}</span>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <Link href={item.href}>{item.action}<span aria-hidden="true"> →</span></Link>
            </li>
          ))}
        </ol>
      </section>

      <section className="boundaryBanner" aria-label="자료 해석 원칙">
        <div>
          <strong>미검출은 미개설이 아닙니다.</strong>
          <p>평가계획에서 과목이 발견되지 않은 경우와 추출 실패, 교육과정 판별 유보를 구분합니다.</p>
        </div>
        <span>교사 검토 원칙</span>
      </section>
    </main>
  );
}
