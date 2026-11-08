import { describe, expect, it } from "vitest";

import { hasStandardCode, MATH_COURSES } from "../app/lib/math-standards";

describe("수학 과목별 성취기준 코드", () => {
  it("두 교육과정의 전체 과목을 제공한다", () => {
    expect(MATH_COURSES["2015"]).toHaveLength(10);
    expect(MATH_COURSES["2022"]).toHaveLength(15);
    expect(MATH_COURSES["2022"]).toContain("공통수학2");
    expect(MATH_COURSES["2022"]).toContain("기하");
    expect(MATH_COURSES["2015"]).toContain("인공지능 수학");
  });

  it("로마 숫자와 공백을 정규화하고 과목 구분을 보존한다", () => {
    expect(hasStandardCode(["[12미적Ⅱ-02-01]"], "12미적II-02-01")).toBe(true);
    expect(hasStandardCode(["[12수학 Ⅰ 01-01]"], "12수학I01-01")).toBe(true);
    expect(hasStandardCode(["[10공수1 − 01 − 01]"], "10공수1-01-01")).toBe(true);
    expect(hasStandardCode(["[10공수1-01-01]"], "10공수2-01-01")).toBe(false);
    expect(hasStandardCode(["[12미적Ⅱ-02-01]"], "12미적I-02-01")).toBe(false);
  });

  it("길이가 다른 코드 일부를 같은 코드로 오인하지 않는다", () => {
    expect(hasStandardCode(["[110공수1-01-01]", "[10공수1-01-010]"], "10공수1-01-01")).toBe(false);
  });
});
