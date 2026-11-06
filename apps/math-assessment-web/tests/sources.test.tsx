import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OfficialSources from "../app/sources/OfficialSources";
import PublicationSnapshot from "../app/sources/PublicationSnapshot";

const payload = {
  schema_version: "1.0.0",
  verified_on: "2026-08-10",
  interpretation: "공식 기준과 학교 사례는 서로 다른 근거다.",
  layers: [
    { level: 1, label: "국가 교육과정 원문", purpose: "성취기준 원문 확인", authority: "교육부 고시" },
    { level: 2, label: "공식 성취수준·평가기준", purpose: "평가 방향 확인", authority: "NCIC" },
    { level: 3, label: "학교 수행평가 운영 사례", purpose: "실제 운영 확인", authority: "학교알리미" },
  ],
  sources: [
    {
      source_id: "source-1",
      layer: 1,
      curriculum: "2022",
      provider: "교육부",
      title: "2022 개정 수학과 교육과정",
      document_type: "국가 교육과정",
      publication_date: "2022-12-22",
      identifier: "교육부 고시 제2022-33호",
      url: "https://www.moe.go.kr/example",
      verification_status: "official_landing_page_verified",
      service_use: "성취기준 원문 확인",
      redistribution: "링크만 제공",
    },
  ],
};

describe("OfficialSources", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders authority layers and official links from the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => payload }));
    render(<OfficialSources />);

    expect(screen.getByRole("status").textContent).toContain("공식 출처 체계를 확인");
    await waitFor(() => expect(screen.getByRole("heading", { name: "자료의 권위와 쓰임을 구분합니다" })).not.toBeNull());
    expect(screen.getAllByText("학교 수행평가 운영 사례")).toHaveLength(2);
    expect(screen.getByText("교육부 고시 제2022-33호")).not.toBeNull();
    expect(screen.getByRole("link", { name: /공식 자료 확인/ }).getAttribute("href")).toBe("https://www.moe.go.kr/example");
  });
});

describe("PublicationSnapshot", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("공개 확정 항목과 검토 중 제외 항목을 구분해 보여 준다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        product: "2026 수학 수행평가 아이디어 아카이브",
        curricula: ["2015 개정", "2022 개정"],
        development_phase: "수학 수행평가 원문 탐색기",
        data_policy: "검토 구간만 공개",
        catalog_ready: true,
        catalog_cases: 9096,
        catalog_subject_groups: 28,
        public_cases: 4979,
        public_items: 10981,
        excluded_items: 13173,
        excluded_reasons: {
          bundle_review: 11206,
          source_mismatch_review: 1568,
          table_structure_review: 399,
        },
      }),
    }));

    render(<PublicationSnapshot />);
    await waitFor(() => expect(screen.getByText("10,981")).not.toBeNull());
    expect(screen.getByText("13,173")).not.toBeNull();
    expect(screen.getByText("원문 구간 경계 재검토")).not.toBeNull();
    expect(screen.getByText("검토 중 항목은 공개 검색에서 제외합니다.")).not.toBeNull();
  });
});
