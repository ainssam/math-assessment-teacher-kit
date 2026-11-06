"use client";

import { useEffect, useRef } from "react";

const TOTAL_RECORDED_KEY = "suhaeng-math-total-visitor-recorded-v2";
const DAILY_RECORDED_PREFIX = "suhaeng-math-daily-visitor-recorded-v2:";

type VisitorCounts = {
  date: string;
  today: number | null;
  total: number | null;
  today_incremented: boolean;
  total_incremented: boolean;
  available: boolean;
};

function koreaDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export default function VisitorCounter() {
  const todayCounter = useRef<HTMLElement>(null);
  const totalCounter = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    const date = koreaDate();
    const dailyKey = `${DAILY_RECORDED_PREFIX}${date}`;
    let incrementToday = true;
    let incrementTotal = true;
    try {
      incrementToday = window.localStorage.getItem(dailyKey) !== "1";
      incrementTotal = window.localStorage.getItem(TOTAL_RECORDED_KEY) !== "1";
    } catch {
      // Storage-disabled browsers still receive the shared counts.
    }

    const parameters = new URLSearchParams({
      increment_today: String(incrementToday),
      increment_total: String(incrementTotal),
    });
    fetch(`/api/v1/visitors?${parameters}`, {
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("visitor counter unavailable");
        return response.json() as Promise<VisitorCounts>;
      })
      .then((payload) => {
        if (todayCounter.current) todayCounter.current.textContent = payload.today?.toLocaleString() ?? "–";
        if (totalCounter.current) totalCounter.current.textContent = payload.total?.toLocaleString() ?? "–";
        try {
          if (payload.today_incremented) window.localStorage.setItem(`${DAILY_RECORDED_PREFIX}${payload.date}`, "1");
          if (payload.total_incremented) window.localStorage.setItem(TOTAL_RECORDED_KEY, "1");
        } catch {
          // Counting remains available even when the browser blocks storage.
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        if (todayCounter.current) todayCounter.current.textContent = "–";
        if (totalCounter.current) totalCounter.current.textContent = "–";
      });

    return () => controller.abort();
  }, []);

  return (
    <span className="visitorCounter" title="개인정보 없이 같은 브라우저를 날짜별 1회, 전체 1회로 집계합니다." aria-live="polite">
      오늘 방문자 <strong ref={todayCounter}>–</strong>명
      <span aria-hidden="true">·</span>
      전체 방문자 <strong ref={totalCounter}>–</strong>명
    </span>
  );
}
