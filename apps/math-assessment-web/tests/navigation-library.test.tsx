import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import RootLayout from "../app/layout";

afterEach(cleanup);

describe("라이브러리 주 메뉴", () => {
  it("유형별 설계 참고와 전체 라이브러리를 분리한다", () => {
    const layout = RootLayout({ children: <main id="main-content">현재 화면</main> });
    const body = layout.props.children;
    render(<>{body.props.children}</>);

    expect(screen.getByRole("link", { name: "유형별 설계 참고" }).getAttribute("href")).toBe("/references");
    expect(screen.getByRole("link", { name: "전체 라이브러리" }).getAttribute("href")).toBe("/cases");
    expect(screen.queryByRole("link", { name: "원문 비교" })).toBeNull();
    expect(screen.queryByRole("link", { name: "교사 검토" })).toBeNull();
  });
});
