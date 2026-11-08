import courses from "./math-courses.json";

export type MathCurriculum = keyof typeof courses;
export const MATH_COURSES: Record<MathCurriculum, string[]> = courses;

export function hasStandardCode(values: string[], key: string): boolean {
  const normalized = values.join(" ").normalize("NFKC").replace(/\s/g, "").replace(/[−–]/g, "-");
  return normalized.match(/(?<![\dA-Za-z])(?:10|12)[가-힣A-Za-z\d]+-?\d{2}-\d{2}(?!\d)/g)?.includes(key) ?? false;
}
