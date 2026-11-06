import { ImageResponse } from "next/og";

export const alt = "2026 수학 수행평가 아이디어 아카이브";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "72px", color: "#37352f", background: "#f7f7f5", fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "18px", fontSize: 30, fontWeight: 700 }}>
          <div style={{ width: 58, height: 58, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 14, color: "white", background: "#202020", fontSize: 34, fontWeight: 900 }}>M</div>
          2026 수학 수행평가 아이디어 아카이브
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          <div style={{ display: "flex", flexDirection: "column", fontSize: 68, fontWeight: 800, letterSpacing: "-0.06em" }}><span>다른 학교 수행평가에서</span><span>수업 아이디어를 찾습니다</span></div>
          <div style={{ fontSize: 28, color: "#5f5e5b" }}>2026학년도 교수·학습 및 평가계획 기반</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: 22, color: "#5f5e5b" }}><span style={{ width: 120, height: 8, background: "#fff176" }} />교사의 최종 판단을 돕는 참고 도구</div>
      </div>
    ),
    size,
  );
}
