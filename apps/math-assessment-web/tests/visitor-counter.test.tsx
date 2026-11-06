import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VisitorCounter from "../app/VisitorCounter";

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      date: "2026-08-12",
      today: 7,
      total: 42,
      today_incremented: true,
      total_incremented: true,
      available: true,
    }),
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("방문자 표시", () => {
  it("오늘 방문자와 전체 방문자를 공용 카운터에서 표시한다", async () => {
    render(<VisitorCounter />);

    await waitFor(() => expect(screen.getByText((_, element) =>
      element?.classList.contains("visitorCounter") === true
        && element.textContent?.replace(/\s+/g, " ") === "오늘 방문자 7명·전체 방문자 42명",
    )).not.toBeNull());

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/visitors?"),
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
    expect(window.localStorage.getItem("suhaeng-math-total-visitor-recorded-v2")).toBe("1");
  });
});
