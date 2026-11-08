export const CURRENT_ACADEMIC_YEAR = 2026;

export default function CasePeriod({ years, semesters }: { years: number[]; semesters: number[] }) {
  const year = years?.length === 1 ? `${years[0]}학년도` : "학년도 미확인";
  const term = semesters?.length === 1 ? `${semesters[0]}학기` :
    semesters?.length === 2 ? "1·2학기 함께 표기" : "학기 미확인";

  return <span className="casePeriod" data-confirmed={years?.length === 1 && Boolean(semesters?.length)}>
    {year}{years?.length !== 1 || !semesters?.length ? " · " : " "}{term}
  </span>;
}
