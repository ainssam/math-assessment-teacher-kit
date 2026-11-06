import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import RootLayout from "../app/layout";

afterEach(cleanup);

describe("주요 메뉴", () => {
  it("교사가 어느 화면에서든 사용설명서로 이동할 수 있다", () => {
    const layout = RootLayout({
      children: <main id="main-content">현재 화면</main>,
    });
    const body = layout.props.children;
    render(<>{body.props.children}</>);

    expect(screen.getByRole("link", { name: "사용설명서" }).getAttribute("href")).toBe(
      "/guide",
    );
  });
});
