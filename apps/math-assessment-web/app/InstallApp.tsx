"use client";

import { useEffect, useRef, useState } from "react";

interface InstallPrompt extends Event {
  prompt(): Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function ServiceWorkerRegistration() {
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      void navigator.serviceWorker.register("/sw.js").catch(() => {
        // Browsing and manual home-screen installation can still work.
      });
    }
  }, []);
  return null;
}

export default function InstallApp() {
  const prompt = useRef<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(false);
  const [showInstructions, setShowInstructions] = useState(false);

  useEffect(() => {
    const displayMode = window.matchMedia?.("(display-mode: standalone)");
    const updateDisplayMode = () => setInstalled(displayMode?.matches === true ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true);
    const capturePrompt = (event: Event) => {
      event.preventDefault();
      prompt.current = event as InstallPrompt;
    };
    const markInstalled = () => {
      prompt.current = null;
      setInstalled(true);
    };
    updateDisplayMode();
    displayMode?.addEventListener("change", updateDisplayMode);
    window.addEventListener("beforeinstallprompt", capturePrompt);
    window.addEventListener("appinstalled", markInstalled);
    return () => {
      displayMode?.removeEventListener("change", updateDisplayMode);
      window.removeEventListener("beforeinstallprompt", capturePrompt);
      window.removeEventListener("appinstalled", markInstalled);
    };
  }, []);

  async function install() {
    const current = prompt.current;
    prompt.current = null;
    if (!current) {
      setShowInstructions(!showInstructions);
      return;
    }
    try {
      const { outcome } = await current.prompt();
      if (outcome === "accepted") setInstalled(true);
    } catch {
      setShowInstructions(true);
    }
  }

  if (installed) return null;

  return (
    <div className="installApp">
      <button type="button" onClick={install} aria-controls="install-instructions" aria-expanded={showInstructions}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" />
        </svg>
        앱으로 설치
      </button>
      <div id="install-instructions" className="installInstructions" hidden={!showInstructions}>
        <p>브라우저 메뉴에서 홈 화면에 추가할 수 있습니다.</p>
        <dl>
          <div><dt>iPhone·iPad Safari</dt><dd>공유 버튼 → 홈 화면에 추가</dd></div>
          <div><dt>Android Chrome</dt><dd>메뉴(⋮) → 앱 설치 또는 홈 화면에 추가</dd></div>
          <div><dt>컴퓨터 Chrome·Edge</dt><dd>주소창의 설치 아이콘 또는 브라우저 메뉴 → 앱 설치</dd></div>
        </dl>
      </div>
    </div>
  );
}
