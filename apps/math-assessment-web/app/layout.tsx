import type { Metadata, Viewport } from "next";
import { Analytics } from "@vercel/analytics/next";
import Link from "./SiteLink";
import { ServiceWorkerRegistration } from "./InstallApp";

import "@fontsource/gowun-dodum/korean.css";
import "katex/dist/katex.min.css";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./globals.css";
import "./design-explorer.css";
import "./standards/standards.css";
import VisitorCounter from "./VisitorCounter";

export const metadata: Metadata = {
  metadataBase: new URL("https://suhaeng-math.vercel.app"),
  title: {
    default: "2026 수학 수행평가 아이디어 아카이브",
    template: "%s | 2026 수학 수행평가 아이디어 아카이브",
  },
  description:
    "2026학년도 교수·학습 및 평가계획에서 다른 학교의 수학 수행평가명과 활동 내용을 찾아보는 교사용 아카이브",
  alternates: { canonical: "/" },
  icons: { apple: "/icons/app-180.png" },
  appleWebApp: { capable: true, title: "수학 수행평가" },
  openGraph: {
    title: "2026 수학 수행평가 아이디어 아카이브",
    description: "2026학년도 교수·학습 및 평가계획에서 수학 수행평가명·활동 내용·평가 기준을 찾아보고 비교합니다.",
    url: "/",
    siteName: "2026 수학 수행평가 아이디어 아카이브",
    locale: "ko_KR",
    type: "website",
  },
};

export const viewport: Viewport = { themeColor: "#1d4ed8" };

const navigation = [
  { href: "/trends", label: "공개자료 경향" },
  { href: "/references", label: "유형별 설계 참고" },
  { href: "/cases", label: "전체 라이브러리" },
  { href: "/guide", label: "사용설명서" },
  { href: "/guide#ai-connection", label: "AI 연결 안내" },
  { href: "/sources", label: "자료 안내" },
];

function releaseDateLabel() {
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "00";
  return `${value("year")}.${value("month")}.${value("day")}`;
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" data-scroll-behavior="smooth">
      <body>
        <a className="skipLink" href="#main-content">본문으로 바로가기</a>
        <header className="siteHeader">
          <div className="headerInner">
            <Link className="brand" href="/" aria-label="2026 수학 수행평가 아이디어 아카이브 홈">
              <svg className="brandLogo" viewBox="0 0 40 40" aria-hidden="true">
                <rect x="1" y="1" width="38" height="38" rx="9" fill="currentColor" />
                <path d="M10.5 27V13.5L20 22l9.5-8.5V27" fill="none" stroke="white" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="20" cy="22" r="2.35" fill="#38bdf8" />
              </svg>
              <span>2026 수학 수행평가 아이디어 아카이브</span>
              <small className="brandUpdatedAt">업데이트 {releaseDateLabel()}</small>
            </Link>
            <nav aria-label="주요 메뉴">
              <ul className="mainNav">
                {navigation.map((item) => (
                  <li key={item.href}><Link href={item.href} className={item.href === "/guide#ai-connection" ? "aiGuideNav" : undefined}>{item.label}</Link></li>
                ))}
              </ul>
            </nav>
          </div>
        </header>
        {children}
        <footer className="siteFooter">
          <div className="footerInner">
            <p>학교알리미 평가계획을 설계 근거로 활용하며, 최종 판단은 교사가 합니다.</p>
            <div className="footerMeta">
              <span>제작 서아인</span>
              <a href="mailto:ainssam@ai.cne.go.kr?subject=%EC%88%98%ED%95%99%20%EC%88%98%ED%96%89%ED%8F%89%EA%B0%80%20%EC%84%A4%EA%B3%84%20%EB%8F%84%EC%9A%B0%EB%AF%B8%20%EC%9E%90%EB%A3%8C%20%EC%A0%95%EC%A0%95%20%EC%9A%94%EC%B2%AD">자료 오류·정정·삭제 요청: ainssam@ai.cne.go.kr</a>
              <Link href="/terms">이용·보호 안내</Link>
              <Link href="/privacy">개인정보 처리방침</Link>
              <VisitorCounter />
            </div>
          </div>
        </footer>
        <ServiceWorkerRegistration />
        {process.env.NEXT_PUBLIC_MATH_ASSESSMENT_ENABLE_ANALYTICS === "1" && <Analytics />}
      </body>
    </html>
  );
}
