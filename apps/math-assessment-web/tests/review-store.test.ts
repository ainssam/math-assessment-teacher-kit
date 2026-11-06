import { describe, expect, it } from "vitest";

import {
  emptyReviewState,
  loadReviewState,
  queueCase,
  removeCase,
  REVIEW_STORAGE_KEY,
  reviewRecord,
  reviewedDimensionCount,
  storeReviewRecord,
} from "../app/review/review-store";

const caseId = "0123456789abcdef01234567";

describe("교사 검토함 저장 구조", () => {
  it("유효한 사례만 중복 없이 담고 제거한다", () => {
    const queued = queueCase(queueCase(emptyReviewState(), caseId), caseId);
    expect(queued.queue).toEqual([caseId]);
    expect(queueCase(queued, "case-1")).toBe(queued);
    expect(removeCase(queued, caseId).queue).toEqual([]);
  });

  it("여섯 기준의 교사 판단과 메모를 사례별로 분리한다", () => {
    const state = queueCase(emptyReviewState(), caseId);
    const record = reviewRecord(state, caseId);
    const next = storeReviewRecord(state, {
      ...record,
      ratings: { ...record.ratings, clarity: "meets", fairness: "question" },
      decision: "hold",
      note: "협업 역할 기준을 원문에서 확인한다.",
      updatedAt: "2026-08-10T00:00:00.000Z",
    });
    expect(reviewedDimensionCount(next.decisions[caseId])).toBe(2);
    expect(next.decisions[caseId].decision).toBe("hold");
  });

  it("손상되거나 범위를 벗어난 로컬 데이터는 안전하게 정리한다", () => {
    const brokenStorage = { getItem: () => "not-json" };
    expect(loadReviewState(brokenStorage)).toEqual(emptyReviewState());

    const unsafeStorage = {
      getItem: (key: string) => key === REVIEW_STORAGE_KEY
        ? JSON.stringify({ version: 1, queue: ["../../secret", caseId], decisions: {} })
        : null,
    };
    expect(loadReviewState(unsafeStorage).queue).toEqual([caseId]);
  });
});
