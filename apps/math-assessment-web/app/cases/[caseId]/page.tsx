import type { Metadata } from "next";

import CaseDetailViewer from "./CaseDetailViewer";

export const metadata: Metadata = {
  title: "수행평가 원문 상세",
  description: "수행평가명, 반영 비율, 평가 방법과 채점 기준을 원문 표로 확인합니다.",
};

export default async function CaseDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ caseId: string }>;
  searchParams: Promise<{ item?: string }>;
}) {
  const { caseId } = await params;
  const { item } = await searchParams;
  return <CaseDetailViewer caseId={caseId} initialItemId={item} />;
}
