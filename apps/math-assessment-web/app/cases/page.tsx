import type { Metadata } from "next";
import { Suspense } from "react";

import CasesExplorer from "./CasesExplorer";

export const metadata: Metadata = {
  title: "전체 수행평가 라이브러리",
  description: "2026학년도 1·2학기 수학 수행평가 사례를 학기, 교육과정, 과목과 지역별로 찾아 비교합니다.",
};

export default function CasesPage() {
  return <Suspense fallback={<div className="routeLoading">전체 라이브러리를 준비하고 있습니다.</div>}><CasesExplorer /></Suspense>;
}
