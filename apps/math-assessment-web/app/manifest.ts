import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "2026 수학 수행평가 아이디어 아카이브",
    short_name: "수학 수행평가",
    description: "수학 수행평가 사례와 채점기준을 찾아보고 비교하는 교사용 아카이브",
    lang: "ko",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#1d4ed8",
    icons: [
      { src: "/icons/app-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/app-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/app-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
