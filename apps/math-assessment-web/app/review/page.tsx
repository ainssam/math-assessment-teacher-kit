import type { Metadata } from "next";
import { Suspense } from "react";

import ReviewWorkspace from "./ReviewWorkspace";

export const metadata: Metadata = {
  title: "교사 검토함",
  description: "수학 수행평가 사례를 동일한 기준으로 읽고 교사의 채택·보류·제외 판단을 기록합니다.",
};

export default function ReviewPage() {
  return <Suspense fallback={<main id="main-content" className="routeLoading">검토함을 준비하고 있습니다.</main>}><ReviewWorkspace /></Suspense>;
}
