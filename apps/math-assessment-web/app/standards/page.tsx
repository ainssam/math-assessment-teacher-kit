import { Suspense } from "react";
import type { Metadata } from "next";

import StandardExplorer from "./StandardExplorer";

export const metadata: Metadata = {
  title: "성취기준으로 과제 비교",
  description: "2015·2022 개정 전체 수학 과목에서 같은 성취기준이 표기된 수행평가의 수행 내용과 채점표를 비교합니다.",
};

export default function StandardsPage() {
  return <Suspense fallback={<p className="routeLoading">성취기준과 사례를 불러오고 있습니다.</p>}><StandardExplorer /></Suspense>;
}
