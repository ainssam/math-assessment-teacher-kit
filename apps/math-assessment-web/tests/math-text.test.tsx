import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import MathText, { normalizeExtractedTex } from "../app/MathText";
import SourceDocumentHtml from "../app/SourceDocumentHtml";

afterEach(cleanup);

describe("추출 수식 표시", () => {
  const extracted = String.raw`\int_{}^{} {\left\{{d} over {dx} f \left( x \right) \right\} dx}`;

  it("한글 문서에서 역슬래시가 빠진 over 표기를 분수로 보정한다", () => {
    expect(normalizeExtractedTex(extracted)).toContain(String.raw`\left\{\frac{d}{dx} f`);
  });

  it("일반 텍스트 안의 달러 수식만 KaTeX로 렌더링한다", () => {
    const { container } = render(<p><MathText text={`비교: $${extracted}$`} /></p>);
    expect(container.textContent).toContain("비교:");
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("원문 HTML 표 안의 수식도 KaTeX로 렌더링한다", async () => {
    const { container } = render(<SourceDocumentHtml html={`<table><tbody><tr><td>$${extracted}$</td></tr></tbody></table>`} />);
    await waitFor(() => expect(container.querySelector(".sourceDocumentHtml .katex")).not.toBeNull());
  });

  it("복잡한 원문 표의 폭·글자·전체 화면을 교사가 직접 조절한다", () => {
    const { container } = render(<SourceDocumentHtml html="<table><tbody><tr><td>평가기준</td></tr></tbody></table>" />);
    const viewer = container.querySelector(".sourceDocumentViewer");

    fireEvent.click(screen.getByRole("button", { name: "표 폭 넓게" }));
    expect(viewer?.classList.contains("isWide")).toBe(true);
    expect(screen.getByRole("button", { name: "기본 표 폭" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "글자 확대" }));
    expect(viewer?.classList.contains("isLargeText")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "전체 화면" }));
    expect(viewer?.classList.contains("isExpanded")).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(viewer?.classList.contains("isExpanded")).toBe(false);
  });
});
