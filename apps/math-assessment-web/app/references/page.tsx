import type { Metadata } from "next";
import { Suspense } from "react";

import ReferenceExplorer from "./ReferenceExplorer";

export const metadata: Metadata = {
  title: "유형별 설계 참고",
  description: "원문 표 제목, 성취기준, 평가 방법과 루브릭을 함께 확인할 수 있는 수학 수행평가 설계 참고 사례입니다.",
};

export default function ReferencesPage() {
  return <Suspense fallback={<div className="routeLoading">유형별 설계 참고를 준비하고 있습니다.</div>}><ReferenceExplorer /></Suspense>;
}
