import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CaseCard, CaseTableRow } from "../app/cases/CasesExplorer";
import type { CaseItem } from "../app/lib/catalog-api";

afterEach(cleanup);

const baseCase: CaseItem = {
  case_id: "case-1",
  curriculum: "2022",
  subject: "미적분Ⅰ",
  curriculum_ambiguous: false,
  curriculum_basis: "explicit",
  school_name: "예시고",
  region: "서울특별시",
  district: "종로구",
  academic_years: [2026],
  grades: [2],
  semesters: [1],
  primary_task_name: "미분과 적분을 활용한 문제 만들기",
  task_names: ["미분과 적분을 활용한 문제 만들기", "극한 그래프 시각화"],
  action_tags: ["문제해결", "수학적모델링"],
  evidence_markers: { rubric: 1, achievement_standard: 1, weight_or_points: 1, assessment_method: 0 },
  evidence_score: 30,
  evidence_excerpt: "가".repeat(500),
  assessment_structure: { overview: "미분과 적분 개념을 활용해 문제를 만들고 해설한다.", methods: ["서술·논술", "프로젝트"], weight: "20점 · 20%", standards: ["12미적01-01"], criteria: ["개념 정확성", "문제 설계"], basis: "table" },
  category: "problem",
  priority_score: 55,
  priority_signals: ["성취기준 연결", "채점기준 확인"],
  source_name: "2026학년도 평가계획",
  source_url: "https://www.schoolinfo.go.kr/example",
  source_sha256: "abc123",
};

describe("사례 카드", () => {
  it("근거 항목 수와 시·군·구 위치를 표시한다", () => {
    render(<CaseCard item={baseCase} />);
    expect(screen.getByText("근거 항목")).not.toBeNull();
    expect(screen.getByTitle("원문에서 확인된 항목 수").textContent).toContain("3/4");
    expect(screen.getByText(/서울특별시 종로구/)).not.toBeNull();
  });

  it("근거 없는 평가영역명은 임의로 과제명처럼 표시하지 않는다", () => {
    render(<CaseCard item={{ ...baseCase, primary_task_name: "수행평가 원문 구간", task_names: [] }} />);
    expect(screen.getByText("원문 확인 대상")).not.toBeNull();
    expect(screen.getByText("평가영역명 원문 확인 필요")).not.toBeNull();
  });

  it("한 학교·과목에서 확인한 수행평가명을 대표 하나로 숨기지 않는다", () => {
    render(<table><tbody><CaseTableRow item={baseCase} /></tbody></table>);
    expect(screen.getByText("확인된 수행평가 2개")).not.toBeNull();
    expect(screen.getByText("미분과 적분을 활용한 문제 만들기")).not.toBeNull();
    expect(screen.getByText("극한 그래프 시각화")).not.toBeNull();
  });
});
