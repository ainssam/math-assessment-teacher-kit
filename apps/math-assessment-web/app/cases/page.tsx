import type { Metadata } from "next";
import { Suspense } from "react";

import CasesExplorer from "./CasesExplorer";

export const metadata: Metadata = {
  title: "전체 수행평가 라이브러리",
  description: "출처가 확인되는 수학 수행평가 사례를 교육과정, 과목, 시도와 시군구별로 찾아 평가 구조 표에서 비교합니다.",
};

export default function CasesPage() {
  return <Suspense fallback={<div className="routeLoading">전체 라이브러리를 준비하고 있습니다.</div>}><CasesExplorer /></Suspense>;
}
