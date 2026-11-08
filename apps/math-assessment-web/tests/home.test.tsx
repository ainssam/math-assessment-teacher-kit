import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Home from "../app/page";

afterEach(cleanup);

describe("수학 수행평가 아이디어 아카이브 시작 화면", () => {
  it("제품 목적과 최신 자료의 진입점을 보여 준다", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /다른 학교 수행평가에서/ })).not.toBeNull();
    expect(screen.getByRole("link", { name: "1·2학기 사례 찾아보기" })).toHaveAttribute("href", "/cases");
    expect(screen.getByText("미검출은 미개설이 아닙니다.")).not.toBeNull();
  });

  it("두 가지 핵심 제품 흐름으로 이동할 수 있다", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: "경향 탐색" }).getAttribute("href")).toBe("/trends");
    expect(screen.getByRole("link", { name: "사례 보기" }).getAttribute("href")).toBe("/cases");
    expect(screen.getByRole("link", { name: "성취기준으로 과제 비교" }).getAttribute("href")).toBe("/standards");
  });

  it("브라우저가 설치 창을 지원하지 않으면 홈 화면 추가 방법을 연다", () => {
    render(<Home />);
    const install = screen.getByRole("button", { name: "앱으로 설치" });
    fireEvent.click(install);
    expect(install).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("iPhone·iPad Safari")).toBeVisible();
  });
});
