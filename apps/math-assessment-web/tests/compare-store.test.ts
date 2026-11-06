import { afterEach, describe, expect, it } from "vitest";

import {
  COMPARE_STORAGE_KEY,
  loadCompareItems,
  MAX_COMPARE_ITEMS,
  saveCompareItems,
  toggleCompareItem,
} from "../app/lib/compare-store";

const IDS = [
  "0000000000000000000000000000",
  "1111111111111111111111111111",
  "2222222222222222222222222222",
  "3333333333333333333333333333",
  "4444444444444444444444444444",
];

afterEach(() => localStorage.clear());

describe("수행평가 비교함", () => {
  it("손상되거나 형식이 다른 항목 ID를 읽지 않는다", () => {
    localStorage.setItem(COMPARE_STORAGE_KEY, JSON.stringify([IDS[0], "case-1", null]));

    expect(loadCompareItems(localStorage)).toEqual([IDS[0]]);
    localStorage.setItem(COMPARE_STORAGE_KEY, "not-json");
    expect(loadCompareItems(localStorage)).toEqual([]);
  });

  it("중복 없이 최대 네 항목만 보관한다", () => {
    expect(saveCompareItems(localStorage, [IDS[0], IDS[0], ...IDS.slice(1)])).toEqual(
      IDS.slice(0, MAX_COMPARE_ITEMS),
    );
  });

  it("같은 항목을 다시 누르면 비교함에서 제거한다", () => {
    expect(toggleCompareItem(localStorage, IDS[0])).toEqual([IDS[0]]);
    expect(toggleCompareItem(localStorage, IDS[0])).toEqual([]);
  });
});
