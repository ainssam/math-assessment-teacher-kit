"use client";

import { useEffect, useState } from "react";

import { fetchCatalog, type ProductMetadata } from "../lib/catalog-api";

const SOURCE_SCHOOLS = 2407;

const reasonLabels: Record<string, string> = {
  bundle_review: "원문 구간 경계 재검토",
  source_mismatch_review: "타 과목·원문 경계 불일치",
  table_structure_review: "표 구조 추가 검토",
};

function number(value: number) {
  return new Intl.NumberFormat("ko-KR").format(value);
}

export default function PublicationSnapshot() {
  const [metadata, setMetadata] = useState<ProductMetadata | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<ProductMetadata>("meta", controller.signal)
      .then((payload) => {
        setMetadata(payload);
        setError("");
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setError(reason.message);
      });
    return () => controller.abort();
  }, []);

  return (
    <section className="sourceSnapshot" aria-labelledby="snapshot-title">
      <div>
        <p className="eyebrow">공개 검증 현황 · 2026.08.15</p>
        <h2 id="snapshot-title">현재 데이터 기준선</h2>
        <p>확정 근거가 있는 항목만 라이브러리에 공개하고, 나머지는 원문 보존 상태로 재검토합니다.</p>
      </div>
      {metadata ? (
        <>
          <dl>
            <div><dt>공개계획 확인 대상</dt><dd>{number(SOURCE_SCHOOLS)}<small>곳</small></dd></div>
            <div><dt>수집 정규화 사례</dt><dd>{number(metadata.catalog_cases)}<small>건</small></dd></div>
            <div><dt>공개 확정 사례</dt><dd>{number(metadata.public_cases)}<small>건</small></dd></div>
            <div><dt>공개 수행평가</dt><dd>{number(metadata.public_items)}<small>건</small></dd></div>
            <div><dt>검토 중·비공개 항목</dt><dd>{number(metadata.excluded_items)}<small>건</small></dd></div>
          </dl>
          <div className="publicationBoundary" aria-label="비공개 검토 사유">
            <strong>검토 중 항목은 공개 검색에서 제외합니다.</strong>
            <ul>
              {Object.entries(metadata.excluded_reasons).map(([reason, count]) => (
                <li key={reason}><span>{reasonLabels[reason] || "추가 근거 검토"}</span><b>{number(count)}건</b></li>
              ))}
            </ul>
            <p>제외 항목은 삭제하거나 임의로 이름을 만들지 않습니다. 원문 경계와 수행평가명이 확인될 때만 공개 목록으로 이동합니다.</p>
          </div>
        </>
      ) : (
        <p className={error ? "snapshotError" : "snapshotLoading"} role={error ? "alert" : "status"}>
          {error || "최신 공개·검토 현황을 불러오고 있습니다."}
        </p>
      )}
    </section>
  );
}
