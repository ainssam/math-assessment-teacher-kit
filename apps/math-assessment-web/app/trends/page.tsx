import type { Metadata } from "next";
import { Suspense } from "react";

import TrendsExplorer from "./TrendsExplorer";

export const metadata: Metadata = {
  title: "수집된 공개자료의 수학 수행평가 경향",
  description: "2015·2022 개정 수학 과목별 수행평가 유형과 근거 현황을 비교합니다.",
};

export default function TrendsPage() {
  return (
    <Suspense fallback={<div className="routeLoading">경향 탐색기를 준비하고 있습니다.</div>}>
      <TrendsExplorer />
    </Suspense>
  );
}
