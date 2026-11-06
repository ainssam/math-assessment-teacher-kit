import Link from "./SiteLink";

type FeaturePreviewProps = {
  eyebrow: string;
  title: string;
  description: string;
  nextMilestone: string;
  items: string[];
};

export default function FeaturePreview({
  eyebrow,
  title,
  description,
  nextMilestone,
  items,
}: FeaturePreviewProps) {
  return (
    <main id="main-content" className="featurePage">
      <section className="featureIntro">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
        <div className="milestoneBadge">현재 상태 · {nextMilestone}</div>
      </section>
      <section className="featureScope" aria-labelledby="feature-scope-title">
        <h2 id="feature-scope-title">이 화면에서 제공할 기능</h2>
        <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
        <p>기능이 완성되기 전까지 실제 분석이나 설계 결과처럼 표시하지 않습니다.</p>
      </section>
      <Link className="backLink" href="/">← 시작 화면으로</Link>
    </main>
  );
}
