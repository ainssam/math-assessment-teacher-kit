import { afterEach, describe, expect, it, vi } from "vitest";

import { apiParameters, fetchCatalog } from "../app/lib/catalog-api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("catalog API", () => {
  it("빈 값은 질의 문자열에서 제외한다", () => {
    expect(apiParameters({ curriculum: "2022", subject: "", page: 2 })).toBe(
      "curriculum=2022&page=2",
    );
  });

  it("일시적인 5xx는 짧게 기다린 뒤 다시 요청한다", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 500 }))
      .mockResolvedValueOnce(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const request = fetchCatalog<{ ok: boolean }>("health");
    await vi.advanceTimersByTimeAsync(300);

    await expect(request).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("존재하지 않는 자료 오류는 다시 요청하지 않는다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({ detail: "자료 없음" }, { status: 404 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCatalog("missing")).rejects.toThrow("자료 없음");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
