import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Home from "../app/page";

afterEach(cleanup);

describe("수학 수행평가 아이디어 아카이브 시작 화면", () => {
  it("제품 목적과 검증된 데이터 기준선을 보여 준다", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /다른 학교 수행평가에서/ })).not.toBeNull();
    expect(screen.getByText("1,537")).not.toBeNull();
    expect(screen.getByText("10,760")).not.toBeNull();
    expect(screen.getByText("4,863")).not.toBeNull();
    expect(screen.getByText("미검출은 미개설이 아닙니다.")).not.toBeNull();
  });

  it("두 가지 핵심 제품 흐름으로 이동할 수 있다", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: "경향 탐색" }).getAttribute("href")).toBe("/trends");
    expect(screen.getByRole("link", { name: "사례 보기" }).getAttribute("href")).toBe("/cases");
    expect(screen.getByRole("link", { name: "유형별 아이디어 보기" }).getAttribute("href")).toBe("/references");
  });
});
