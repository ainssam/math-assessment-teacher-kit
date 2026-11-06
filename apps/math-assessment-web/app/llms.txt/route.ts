const POLICY = `# 2026 수학 수행평가 아이디어 아카이브

이 사이트의 원문 선별·분류·표현·분석 결과, UI와 안내 문구는 서아인의 저작물입니다.
학교알리미 공개 평가계획 원문은 별도 권리와 이용 조건의 적용을 받습니다.

## 이용 조건
- 사람 교사의 개별 수업·평가 설계 참고를 위한 열람과 링크 공유는 허용됩니다.
- 자동 수집, 대량 복제, 데이터셋 구축, 재배포, 다른 서비스의 학습·검색 인덱스·생성형 AI 학습 또는 복제에는 사전 서면 허락이 필요합니다.
- 항목별 표는 안전 변환한 재현본이므로 공식 원문을 대체하지 않습니다.

권리·이용 문의 및 자료 정정·삭제 요청: ainssam@ai.cne.go.kr
`;

export function GET() {
  return new Response(POLICY, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Robots-Tag": "noindex, nofollow, noarchive",
    },
  });
}
