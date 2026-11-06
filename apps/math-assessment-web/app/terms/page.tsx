import type { Metadata } from "next";
import Link from "../SiteLink";

export const metadata: Metadata = {
  title: "이용·보호 안내",
  description: "2026 수학 수행평가 아이디어 아카이브의 자료 이용 범위와 보호 안내입니다.",
};

export default function TermsPage() {
  return (
    <main id="main-content" className="policyPage">
      <p className="eyebrow">이용·보호 안내 · 2026. 8. 13.</p>
      <h1>설계 근거는 함께 보고, 복제는 허락을 받습니다</h1>
      <p className="policyLead">이 도구는 학교알리미 공개 평가계획을 교사의 설계 판단에 참고할 수 있게 정리한 서비스입니다. 최종 판단과 적용 책임은 교사에게 있습니다.</p>

      <section><h2>1. 권리와 공개 자료의 구분</h2><p>서비스의 선별·분류 체계, 원문 경계 판별·안전 변환 방식, 교사용 화면·문구·보고서·코드는 서아인에게 권리가 있습니다. 학교알리미 평가계획과 공식 교육과정 자료는 각 공개 주체와 원저작자의 권리·이용 조건이 적용되며, 이 서비스가 그 원문 전체의 권리를 주장하지 않습니다.</p></section>
      <section><h2>2. 허용하는 이용</h2><p>누구나 개별 교사의 수업·평가 설계 참고를 위해 화면을 열람하고, 서비스 링크를 공유할 수 있습니다. 표시된 항목은 공식 원문과 대조하고 학교 학업성적관리규정에 맞게 다시 설계해 사용하세요.</p></section>
      <section><h2>3. 사전 허락이 필요한 이용</h2><p>자동화된 대량 수집, 표·분석 결과의 데이터셋화, 다른 웹서비스·출판물·연수 자료에의 재배포, 화면·분류 체계의 실질적 복제, 생성형 AI 학습·파인튜닝·검색 인덱스 구축에는 사전 서면 허락이 필요합니다. 이 조건은 공식 원문 자체의 별도 이용 조건을 대신하지 않습니다.</p></section>
      <section><h2>4. 원문과 정확성</h2><p>화면의 표는 지면 배치와 일부 형식을 단순화한 안전 변환 재현본입니다. 경계가 확실하지 않은 자료는 원문 HTML을 제공하지 않으며 공개 학교알리미 링크만 안내합니다. 오류를 발견하면 확인 후 정정·삭제할 수 있도록 알려 주세요.</p></section>
      <section><h2>5. 문의와 정정·삭제 요청</h2><p><strong>제작·운영: 서아인</strong><br /><a href="mailto:ainssam@ai.cne.go.kr">ainssam@ai.cne.go.kr</a></p></section>
      <p className="policyBack"><Link href="/">← 서비스로 돌아가기</Link></p>
    </main>
  );
}
