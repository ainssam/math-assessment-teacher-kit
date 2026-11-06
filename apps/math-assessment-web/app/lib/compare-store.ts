export const COMPARE_STORAGE_KEY = "math-assessment-compare-v1";
export const MAX_COMPARE_ITEMS = 4;

export function loadCompareItems(storage: Storage): string[] {
  try {
    const value = JSON.parse(storage.getItem(COMPARE_STORAGE_KEY) || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is string => /^[0-9a-f]{28}$/.test(String(item))).slice(0, MAX_COMPARE_ITEMS);
  } catch {
    return [];
  }
}

export function saveCompareItems(storage: Storage, itemIds: string[]) {
  const unique = [...new Set(itemIds)].slice(0, MAX_COMPARE_ITEMS);
  storage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(unique));
  return unique;
}

export function toggleCompareItem(storage: Storage, itemId: string) {
  const current = loadCompareItems(storage);
  if (current.includes(itemId)) {
    return saveCompareItems(storage, current.filter((value) => value !== itemId));
  }
  if (current.length >= MAX_COMPARE_ITEMS) return current;
  return saveCompareItems(storage, [...current, itemId]);
}

