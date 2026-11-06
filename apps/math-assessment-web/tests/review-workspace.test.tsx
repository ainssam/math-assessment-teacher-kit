import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewWorkspace from "../app/review/ReviewWorkspace";

const caseId = "0123456789abcdef01234567";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(`case=${caseId}`),
}));

const caseItem = {
  case_id: caseId,
  curriculum: "2022",
  subject: "미적분Ⅰ",
  curriculum_ambiguous: false,
  curriculum_basis: "explicit",
  school_name: "예시고",
  region: "서울",
  academic_years: [2026],
  grades: [2],
  semesters: [1],
  primary_task_name: "변화율을 활용한 실생활 모델링",
  task_names: ["변화율을 활용한 실생활 모델링"],
  action_tags: ["수학적모델링"],
  evidence_markers: { rubric: 1, achievement_standard: 1, weight_or_points: 1, assessment_method: 1 },
  evidence_score: 40,
  evidence_excerpt: "상황을 함수로 표현하고 변화율의 의미를 설명한다.",
  source_name: "2026학년도 평가계획",
  source_url: "https://www.schoolinfo.go.kr/example",
  source_sha256: "a".repeat(64),
};

describe("교사 검토함", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("요청한 사례를 담고 여섯 검토 기준을 보여 준다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => caseItem }));
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "변화율을 활용한 실생활 모델링" })).not.toBeNull());
    expect(screen.getAllByRole("combobox")).toHaveLength(6);
    expect(screen.getByText("과제 명료성")).not.toBeNull();
    expect(screen.getByText("공정성")).not.toBeNull();
    expect(screen.getByRole("button", { name: "교사 검토 저장" })).not.toBeNull();
  });
});
