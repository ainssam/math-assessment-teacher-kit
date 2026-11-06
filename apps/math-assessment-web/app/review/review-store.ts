export const REVIEW_STORAGE_KEY = "math-assessment-review-queue-v1";
export const MAX_REVIEW_CASES = 25;

export const REVIEW_DIMENSIONS = [
  { id: "clarity", label: "과제 명료성", prompt: "학생이 무엇을 해야 하고 무엇을 제출할지 분명한가요?" },
  { id: "mathematical_thinking", label: "수학적 사고", prompt: "단순 정리보다 추론·표현·문제해결 과정이 드러나나요?" },
  { id: "process_evidence", label: "과정 증거", prompt: "최종 결과 외에 수업 중 확인할 증거가 있나요?" },
  { id: "alignment", label: "평가 정합성", prompt: "과제·평가 요소·루브릭이 같은 역량을 확인하나요?" },
  { id: "fairness", label: "공정성", prompt: "도구·협업·가정 환경에 따른 불리함을 줄였나요?" },
  { id: "feasibility", label: "실행 가능성", prompt: "제시된 차시와 학교 여건에서 운영·채점할 수 있나요?" },
] as const;

export type ReviewDimensionId = (typeof REVIEW_DIMENSIONS)[number]["id"];
export type ReviewRating = "unreviewed" | "meets" | "question" | "needs_work";
export type ReviewDecision = "pending" | "adopt" | "hold" | "exclude";

export type ReviewRecord = {
  caseId: string;
  ratings: Record<ReviewDimensionId, ReviewRating>;
  decision: ReviewDecision;
  note: string;
  updatedAt: string;
};

export type ReviewState = {
  version: 1;
  queue: string[];
  decisions: Record<string, ReviewRecord>;
};

const CASE_ID_PATTERN = /^[0-9a-f]{24}$/;
const RATING_VALUES = new Set<ReviewRating>(["unreviewed", "meets", "question", "needs_work"]);
const DECISION_VALUES = new Set<ReviewDecision>(["pending", "adopt", "hold", "exclude"]);

export function emptyRatings(): ReviewRecord["ratings"] {
  return Object.fromEntries(REVIEW_DIMENSIONS.map(({ id }) => [id, "unreviewed"])) as ReviewRecord["ratings"];
}

export function emptyReviewState(): ReviewState {
  return { version: 1, queue: [], decisions: {} };
}

export function loadReviewState(storage: Pick<Storage, "getItem">): ReviewState {
  const raw = storage.getItem(REVIEW_STORAGE_KEY);
  if (!raw) return emptyReviewState();
  try {
    const candidate = JSON.parse(raw) as Partial<ReviewState>;
    const queue = Array.isArray(candidate.queue)
      ? [...new Set(candidate.queue.filter((value): value is string => typeof value === "string" && CASE_ID_PATTERN.test(value)))].slice(0, MAX_REVIEW_CASES)
      : [];
    const decisions: ReviewState["decisions"] = {};
    for (const caseId of queue) {
      const source = candidate.decisions?.[caseId];
      if (!source) continue;
      const ratings = emptyRatings();
      for (const dimension of REVIEW_DIMENSIONS) {
        const value = source.ratings?.[dimension.id];
        if (RATING_VALUES.has(value)) ratings[dimension.id] = value;
      }
      decisions[caseId] = {
        caseId,
        ratings,
        decision: DECISION_VALUES.has(source.decision) ? source.decision : "pending",
        note: typeof source.note === "string" ? source.note.slice(0, 2000) : "",
        updatedAt: typeof source.updatedAt === "string" ? source.updatedAt : "",
      };
    }
    return { version: 1, queue, decisions };
  } catch {
    return emptyReviewState();
  }
}

export function saveReviewState(storage: Pick<Storage, "setItem">, state: ReviewState) {
  storage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(state));
}

export function queueCase(state: ReviewState, caseId: string): ReviewState {
  if (!CASE_ID_PATTERN.test(caseId) || state.queue.includes(caseId)) return state;
  return { ...state, queue: [...state.queue, caseId].slice(0, MAX_REVIEW_CASES) };
}

export function removeCase(state: ReviewState, caseId: string): ReviewState {
  const decisions = { ...state.decisions };
  delete decisions[caseId];
  return { ...state, queue: state.queue.filter((value) => value !== caseId), decisions };
}

export function reviewRecord(state: ReviewState, caseId: string): ReviewRecord {
  return state.decisions[caseId] ?? {
    caseId,
    ratings: emptyRatings(),
    decision: "pending",
    note: "",
    updatedAt: "",
  };
}

export function storeReviewRecord(state: ReviewState, record: ReviewRecord): ReviewState {
  const queued = queueCase(state, record.caseId);
  return { ...queued, decisions: { ...queued.decisions, [record.caseId]: record } };
}

export function reviewedDimensionCount(record: ReviewRecord) {
  return REVIEW_DIMENSIONS.filter(({ id }) => record.ratings[id] !== "unreviewed").length;
}
