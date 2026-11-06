import type { Metadata } from "next";

import AssessmentCompare from "./AssessmentCompare";

export const metadata: Metadata = {
  title: "수행평가 원문 비교",
  description: "학교별 수행평가명, 반영 비율, 평가 방법과 루브릭을 나란히 비교합니다.",
};

export default function ComparePage() {
  return <AssessmentCompare />;
}

