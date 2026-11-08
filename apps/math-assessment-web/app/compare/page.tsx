import type { Metadata } from "next";

import AssessmentCompare from "./AssessmentCompare";

export const metadata: Metadata = {
  title: "수행평가 원문 비교",
  description: "학교별 수행평가명, 반영 비율, 평가 방법과 루브릭을 나란히 비교합니다.",
};

export default async function ComparePage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const raw = typeof query.items === "string" ? query.items : undefined;
  const ids = raw === undefined ? undefined : [...new Set(raw.split(","))]
    .filter((id) => /^[0-9a-f]{28}$/.test(id)).slice(0, 4);
  return <AssessmentCompare requestedIds={ids}
    curriculum={query.curriculum === "2015" ? "2015" : "2022"}
    standard={typeof query.standard === "string" ? query.standard.slice(0, 32) : ""}
    subject={typeof query.subject === "string" ? query.subject.slice(0, 40) : ""} />;
}

