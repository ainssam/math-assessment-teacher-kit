import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import SourceDocumentHtml from "../app/SourceDocumentHtml";
import { sourceTableKey } from "../app/lib/source-table-segmentation";

afterEach(cleanup);
const previews = [{ url: `/source-tables/${"a".repeat(64)}.webp`, page: 17, width: 1024, height: 1351 }];
const html = "<table><tr><th>평가요소</th><td>근거를 설명함</td></tr></table>";

describe("원문 표 이미지", () => {
  it("문단으로 풀린 수식도 전체 원문 대응이 확인된 경우에만 접는다", () => {
    const damaged = "<p>함수 의 증감표와 그래프를 작성한다.</p><p>별도 채점 안내</p>";
    const { rerender } = render(<SourceDocumentHtml html={damaged} previews={previews} />);
    expect(screen.getByText("별도 채점 안내")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("원문 대조가 필요합니다");
    rerender(<SourceDocumentHtml html={damaged} previews={previews} coveredExcerpt />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("추출 표 함께 보기").closest("details")!.open).toBe(false);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText("별도 채점 안내")).toBeVisible();
    expect(screen.getAllByRole("status").some((node) => node.textContent?.includes("원문 대조가 필요합니다"))).toBe(true);
  });
  it("원문을 먼저 보여 주고 추출 표를 별도로 보존한다", () => {
    render(<SourceDocumentHtml html={html} previews={previews} coveredExcerpt />);
    expect(screen.getByRole("img", { name: "수행평가 원문 표 1, 원문 17쪽" })).toBeVisible();
    expect(screen.getByText("원문 17쪽 · 표 1")).toBeVisible();
    const extracted = screen.getByText("추출 표 함께 보기").closest("details")!;
    expect(extracted.open).toBe(false);
    expect(extracted.textContent).toContain("근거를 설명함");
  });

  it("이미지를 불러오지 못하면 안내와 함께 추출 표를 연다", () => {
    render(<SourceDocumentHtml html={html} previews={previews} coveredExcerpt />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByRole("status")).toHaveTextContent("원문 표를 불러오지 못했습니다");
    expect(screen.getByText("추출 표 함께 보기").closest("details")!.open).toBe(true);
    expect(screen.getByText("근거를 설명함")).toBeVisible();
  });

  it("이전 자료의 이미지 오류가 다음 자료를 가리지 않는다", () => {
    const { rerender } = render(<SourceDocumentHtml html={html} previews={previews} coveredExcerpt />);
    fireEvent.error(screen.getByRole("img"));
    rerender(<SourceDocumentHtml html={html} previews={[{ ...previews[0], url: `/source-tables/${"b".repeat(64)}.webp` }]} coveredExcerpt />);
    expect(screen.getByRole("img")).toBeVisible();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("원문 이미지가 없는 자료는 기존 표 보기를 유지한다", () => {
    render(<SourceDocumentHtml html={html} />);
    expect(screen.getByText("근거를 설명함")).toBeVisible();
    expect(screen.queryByText("추출 표 함께 보기")).toBeNull();
    expect(screen.getByRole("button", { name: "전체 화면", exact: true })).toBeVisible();
  });

  it("미복원 수식은 알리고 원문으로 복원한 표의 숨긴 추출문은 경고하지 않는다", () => {
    const damaged = "<table><tr><td>성취도 를 원문 수식에 대입</td></tr></table>";
    const { rerender } = render(<SourceDocumentHtml html={damaged} />);
    expect(screen.getByRole("status")).toHaveTextContent("원문 대조가 필요합니다");
    rerender(<SourceDocumentHtml html={damaged} previews={previews} coveredTableKeys={[sourceTableKey("성취도 를 원문 수식에 대입")]} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("페이지 전체와 한글 렌더링은 표 조각과 구분해 표시한다", () => {
    render(<SourceDocumentHtml html={html} previews={[{ ...previews[0], page_context: true, rendered_from_hangul: true }]} />);
    expect(screen.getByRole("img", { name: "수행평가가 포함된 원문 17쪽" })).toBeVisible();
    expect(screen.getByText(/한글 원문 렌더링 17쪽/)).toHaveTextContent("같은 페이지의 다른 평가나 안내가 함께 보일 수 있습니다");
  });

  it("원문으로 확인된 표만 접고 나머지 표와 설명을 계속 보여 준다", () => {
    const key = sourceTableKey("평가요소근거를 설명함");
    render(<SourceDocumentHtml html={html + "<p>누락하면 안 되는 별도 안내</p><table><tr><td>추가 과제 배점 20점</td></tr></table>"}
      previews={previews} coveredTableKeys={[key]} />);
    const fallback = screen.getByText("대응하는 추출 표 함께 보기").closest("details")!;
    expect(fallback.open).toBe(false);
    expect(fallback.textContent).toContain("근거를 설명함");
    expect(screen.getByText("누락하면 안 되는 별도 안내")).toBeVisible();
    expect(screen.getByText("추가 과제 배점 20점")).toBeVisible();
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText("근거를 설명함")).toBeVisible();
    expect(screen.queryByText("대응하는 추출 표 함께 보기")).toBeNull();
  });
});
