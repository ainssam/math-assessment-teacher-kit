import { describe, expect, it } from "vitest";

import { segmentSourceTables } from "../app/lib/source-table-segmentation";

describe("원문 표 구획 분리", () => {
  it("빈 세로 여백과 겹친 PDF 내용 셀만 경계까지 줄이고 문장은 보존한다", () => {
    const source = `<table><tr><th>성취기준</th><th>수준</th><th>내용</th><td rowspan="3"></td></tr>
      <tr><td rowspan="2">[10공수1-02-07]</td><td>A</td><td colspan="2" rowspan="2">삼차방정식을 풀고 과정을 설명한다.</td></tr>
      <tr><td>B</td></tr></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    expect(result.clippedColspanCount).toBe(1);
    const cell = container.querySelector('[data-source-colspan-clipped="true"]') as HTMLTableCellElement;
    expect(cell.colSpan).toBe(1);
    expect(cell.rowSpan).toBe(2);
    expect(cell.textContent).toBe("삼차방정식을 풀고 과정을 설명한다.");
    expect(container.textContent).toContain("[10공수1-02-07]");
  });

  it("다른 내용 셀과 충돌하는 병합은 임의로 줄이지 않는다", () => {
    const source = `<table><tr><td>첫 열</td><td rowspan="2">보존할 내용</td></tr>
      <tr><td colspan="2">다른 내용</td></tr></table>`;
    const result = segmentSourceTables(source);
    expect(result.clippedColspanCount).toBe(0);
    expect(result.html).toContain('colspan="2"');
    expect(result.html).toContain("보존할 내용");
  });

  it("공통수학과 기본수학의 표 밖 성취기준 코드도 함께 읽게 묶는다", () => {
    const source = `<p>[10공수1-01-01]</p><p>[10공수1-01-02]</p><h2>다음</h2>
      <p>[10기수2-01-01]</p><p>[10기수2-01-02]</p>`;
    const result = segmentSourceTables(source);
    expect(result.orphanStandardGroupCount).toBe(2);
    expect(result.html).toContain("[10공수1-01-02]");
    expect(result.html).toContain("[10기수2-01-02]");
  });
  it("긴 결합 표를 원문 표제어에 따라 별도 표로 나눈다", () => {
    const source = `<p>원문 제목</p><table><tbody>
      <tr><th>평가 영역명</th><td>함수 탐구</td></tr>
      <tr><td>수행과제</td><td>탐구 보고서 작성</td></tr>
      <tr><td>성취기준</td><td>성취기준별 성취수준</td></tr>
      <tr><td>[12대수01-01]</td><td>A 수준</td></tr>
      <tr><td></td><td>B 수준</td></tr>
      <tr><td>평가 방법</td><td>프로젝트</td></tr>
      <tr><td></td><td>교사 관찰</td></tr>
      <tr><td>평가 요소</td><td>수행 수준(채점 기준)</td><td>척도</td><td>배점</td></tr>
      <tr><td>논리성</td><td>충족</td><td>상</td><td>10점</td></tr>
    </tbody></table>`;

    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result).toMatchObject({ splitTableCount: 1, sectionCount: 4 });
    expect(container.querySelectorAll(".sourceTableSection")).toHaveLength(4);
    expect(container.querySelectorAll(".sourceTableSection table")).toHaveLength(4);
    expect(Array.from(container.querySelectorAll(".sourceTableSection > h3")).map((node) => node.textContent)).toEqual([
      "평가 개요·수행과제",
      "성취기준·성취수준",
      "평가 방법·운영",
      "채점 기준·배점",
    ]);
    expect(container.textContent).toContain("탐구 보고서 작성");
    expect(container.textContent).toContain("10점");
  });

  it("짧거나 구획 표제어가 없는 표는 원형을 유지한다", () => {
    const source = "<table><tbody><tr><td>항목</td><td>내용</td></tr><tr><td>1</td><td>원문</td></tr></tbody></table>";
    const result = segmentSourceTables(source);

    expect(result.splitTableCount).toBe(0);
    expect(result.sectionCount).toBe(0);
    expect(result.html).toContain("<table>");
  });

  it("구획 경계를 가로지르는 세로 병합 셀을 각 표 높이에 맞춰 이어 붙인다", () => {
    const source = `<table><tbody>
      <tr><th rowspan="4">공통 항목</th><th>평가 영역명</th><td>탐구</td></tr>
      <tr><th>수행과제</th><td>보고서</td></tr>
      <tr><th>성취기준</th><td>성취기준별 성취수준</td></tr>
      <tr><td>[12대수01-01]</td><td>A 수준</td></tr>
      <tr><td rowspan="2">평가 방법</td><td>프로젝트</td></tr>
      <tr><td>교사 관찰</td></tr>
      <tr><td>평가 요소</td><td>수행 수준</td><td>척도</td><td>배점</td></tr>
      <tr><td rowspan="2">논리성</td><td>충족</td><td>상</td><td>10점</td></tr>
      <tr><td>부분 충족</td><td>중</td><td>7점</td></tr>
    </tbody></table>`;

    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    const sections = Array.from(container.querySelectorAll(".sourceTableSection"));

    expect(result.sectionCount).toBe(4);
    expect(sections[0].querySelector('[rowspan="2"]')?.textContent).toContain("공통 항목");
    expect(sections[1].querySelector('[data-source-rowspan-continuation="true"]')?.textContent).toContain("공통 항목");
    for (const section of sections) {
      const rowCount = section.querySelectorAll("tbody > tr").length;
      for (const cell of section.querySelectorAll<HTMLElement>("[rowspan]")) {
        expect(Number(cell.getAttribute("rowspan"))).toBeLessThanOrEqual(rowCount);
      }
    }
  });

  it("첫 셀이 비어 있어도 뒤쪽 성취기준 표제어로 구획을 판단한다", () => {
    const source = `<table><tbody>
      <tr><th></th><th>성취기준</th><th>성취기준별 성취수준</th></tr>
      <tr><td></td><td>[12대수01-01]</td><td>A 수준</td></tr>
      <tr><td></td><td></td><td>B 수준</td></tr>
      <tr><td></td><td></td><td>C 수준</td></tr>
      <tr><td>평가 방법</td><td colspan="2">프로젝트</td></tr>
      <tr><td></td><td colspan="2">교사 관찰</td></tr>
      <tr><td>평가 요소</td><td>수행 수준</td><td>배점</td></tr>
      <tr><td>논리성</td><td>충족</td><td>10점</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(Array.from(container.querySelectorAll(".sourceTableSection > h3")).map((node) => node.textContent)).toEqual([
      "성취기준·성취수준",
      "평가 방법·운영",
      "채점 기준·배점",
    ]);
  });

  it("같은 머리글이 반복된 페이지별 표 조각을 한 표로 합친다", () => {
    const header = "<tr><th>영역</th><th>성취기준</th><th>평가기준</th><th>평가기준</th></tr>";
    const source = `<table><tbody>${header}<tr><td>생활경제</td><td>[12경수01-01]</td><td>상</td><td>설명</td></tr></tbody></table>
      <table><tbody>${header}<tr><td>생활경제</td><td>[12경수01-01]</td><td>중</td><td>이해</td></tr></tbody></table>
      <table><tbody>${header}<tr><td>생활경제</td><td>[12경수01-01]</td><td>하</td><td>확인</td></tr></tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.mergedFragmentCount).toBe(2);
    expect(container.querySelectorAll("table")).toHaveLength(1);
    expect(container.querySelectorAll("tr")).toHaveLength(4);
    expect(container.textContent).toContain("설명");
    expect(container.textContent).toContain("이해");
    expect(container.textContent).toContain("확인");
  });

  it("오른쪽 문장 끝만 떨어진 빈 표 조각을 앞 표의 대응 셀에 되붙인다", () => {
    const source = `<table><tbody>
      <tr><th>배점</th><th>채점 기준</th></tr>
      <tr><td>100</td><td>6가지 기준을</td></tr>
      <tr><td>90</td><td>5가지 기준을</td></tr>
      <tr><td>80</td><td>4가지 기준을</td></tr>
    </tbody></table><h4>공동체</h4><table><tbody>
      <tr><th></th><th></th></tr>
      <tr><td></td><td>충족하였음</td></tr>
      <tr><td></td><td>충족하였음</td></tr>
      <tr><td></td><td>충족하였음</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.reconstructedCellCount).toBe(3);
    expect(container.querySelectorAll("table")).toHaveLength(1);
    expect(container.textContent).toContain("6가지 기준을 충족하였음");
    expect(container.querySelector(".sourceRecoveredFragmentNotes")?.textContent).toContain("공동체");
  });

  it("표 밖에 연속으로 떨어진 성취기준 코드를 별도 근거 상자로 묶는다", () => {
    const source = `<p>[12대수02-02]</p><h4>[12대수03-07] [12대수03-03]</h4><p>[12대수03-04]</p><table><tr><td>원문 표</td></tr></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.orphanStandardGroupCount).toBe(1);
    expect(container.querySelectorAll(".sourceOrphanStandards span")).toHaveLength(3);
    expect(container.querySelector(".sourceOrphanStandards")?.textContent).toContain("[12대수03-04]");
  });

  it("표 뒤에 연속으로 잘린 짧은 문구를 큰 제목 대신 원문 메모로 보존한다", () => {
    const source = `<table><tr><td>원문 표</td></tr></table><h4>만점의</h4><h4>답변을</h4>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.recoveredNoteGroupCount).toBe(1);
    expect(container.querySelectorAll("h4")).toHaveLength(0);
    expect(container.querySelector(".sourceRecoveredFragmentNotes")?.textContent).toContain("만점의답변을");
  });

  it("페이지 중간에서 A~E 성취수준으로 시작한 표 조각도 성취기준 구획으로 표시한다", () => {
    const source = `<table><tbody>
      <tr><td>D</td><td>간단한 지수함수의 그래프를 그릴 수 있다.</td></tr>
      <tr><td>E</td><td>안내된 절차에 따라 그래프를 그릴 수 있다.</td></tr>
      <tr><td>[12대수02-02]</td><td>A</td><td>삼각함수의 성질을 설명할 수 있다.</td></tr>
      <tr><td></td><td>B</td><td>삼각함수의 성질을 이해한다.</td></tr>
      <tr><td></td><td>C</td><td>삼각함수의 성질을 안다.</td></tr>
      <tr><td></td><td>D</td><td>간단한 그래프를 그릴 수 있다.</td></tr>
      <tr><td></td><td>E</td><td>안내된 절차에 따라 그래프를 그릴 수 있다.</td></tr>
      <tr><td>평가 영역명</td><td colspan="2">새 수행평가</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(Array.from(container.querySelectorAll(".sourceTableSection > h3")).map((node) => node.textContent)).toEqual([
      "성취기준·성취수준",
      "평가 개요·수행과제",
    ]);
  });

  it("실제 표 행 수를 넘어가는 세로 병합값은 마지막 행까지만 보이도록 제한한다", () => {
    const source = `<table><tbody><tr><td rowspan="8">공통</td><td>상</td></tr><tr><td>중</td></tr><tr><td>하</td></tr></tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.clampedRowspanCount).toBe(1);
    expect(container.querySelector("[data-source-rowspan-clamped]")?.getAttribute("rowspan")).toBe("3");
  });

  it("페이지 경계에서 A-C와 D-E로 끊긴 성취수준 행을 앞 표에 이어 붙인다", () => {
    const source = `<table><tbody>
      <tr><th rowspan="5">[10공수1-01-02] 항등식의 성질을 이해한다.</th><td>A</td><td>다양한 문제를 해결할 수 있다.</td></tr>
      <tr><td>B</td><td>문제를 해결할 수 있다.</td></tr>
      <tr><td>C</td><td>간단한 문제를 해결할 수 있다.</td></tr>
    </tbody></table><table><tbody>
      <tr><td></td><td>D</td><td>안내된 절차로 해결할 수 있다.</td></tr>
      <tr><td></td><td>E</td><td>뜻을 안다.</td></tr>
      <tr><td>[10공수1-01-03]</td><td>A</td><td>인수분해를 할 수 있다.</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    const tables = container.querySelectorAll("table");

    expect(result.gradeContinuationRowCount).toBe(2);
    expect(tables).toHaveLength(2);
    expect(Array.from(tables[0].querySelectorAll("tr")).map((row) => row.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining("D안내된 절차"), expect.stringContaining("E뜻을 안다")]),
    );
    expect(tables[1].textContent).not.toContain("안내된 절차");
    expect(tables[0].querySelector('[rowspan="5"]')).not.toBeNull();
  });

  it("D-E 앞에 놓인 한 줄짜리 페이지 연속 문구도 같은 표로 옮겨 보존한다", () => {
    const source = `<table><tbody>
      <tr><th rowspan="6">성취기준 [12인수01-01]</th><td>A</td><td>다양한 문제를 해결할 수 있다.</td></tr>
      <tr><td>B</td><td>문제를 해결할 수 있다.</td></tr>
      <tr><td>C</td><td>손실함수의 뜻을 이해하고 설명할 수 있다.</td></tr>
    </tbody></table><h3>다음 페이지</h3><table><tbody>
      <tr><td></td><td></td><td>최적화된 추세선을 찾을 수 있다.</td></tr>
      <tr><td></td><td>D</td><td>안내된 절차로 해결할 수 있다.</td></tr>
      <tr><td></td><td>E</td><td>뜻을 안다.</td></tr>
      <tr><td>평가 방법</td><td colspan="2">논술</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    const firstTable = container.querySelector("table")!;

    expect(result.gradeContinuationRowCount).toBe(2);
    expect(firstTable.textContent).toContain("최적화된 추세선을 찾을 수 있다.");
    expect(firstTable.textContent).toContain("D안내된 절차");
    expect(firstTable.textContent).toContain("E뜻을 안다");
    expect(firstTable.querySelector('[data-source-page-continuation="true"]')).not.toBeNull();
  });

  it("구획 분리 뒤 새로 드러난 A-C와 D-E 경계도 한 표로 복원한다", () => {
    const source = `<table><tbody>
      <tr><th>성취기준</th><th>성취기준별 성취수준</th></tr>
      <tr><th rowspan="5">[12대수01-01] 거듭제곱의 뜻을 설명할 수 있다.</th><td>A</td><td>다양한 계산을 할 수 있다.</td></tr>
      <tr><td>B</td><td>계산을 할 수 있다.</td></tr>
      <tr><td>C</td><td>간단한 계산을 할 수 있다.</td></tr>
      <tr><td>평가 방법</td><td>D</td><td>안내된 절차로 계산할 수 있다.</td></tr>
      <tr><td>E</td><td>뜻을 안다.</td></tr>
      <tr><td>평가 요소 및 채점 기준</td><td colspan="2">풀이 과정을 평가한다.</td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.gradeContinuationRowCount).toBe(2);
    expect(container.querySelector('[data-source-merged-grade-continuation="true"]')?.textContent).toContain("E뜻을 안다");
  });

  it("한 구획에서 끝까지 비어 있는 오른쪽 열만 제거한다", () => {
    const source = `<table><tbody><tr>
      <th>성취기준 및 성취수준</th>
      <td>[12대수01-01] 거듭제곱의 뜻을 알고 설명할 수 있다. A 수준에서는 그 뜻과 성질을 설명하고 계산할 수 있다.
      [12대수01-02] 지수가 유리수와 실수까지 확장될 수 있음을 이해하고 설명할 수 있다.
      [12대수01-03] 지수법칙을 이해하고 이를 이용하여 다양한 식을 간단히 나타낼 수 있다.
      [12대수01-04] 로그의 뜻을 알고 그 성질을 이용하여 계산할 수 있다.</td>
      <td></td><td></td><td></td><td></td>
    </tr></tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    const table = container.querySelector("table")!;

    expect(result.prunedTrailingColumnCount).toBe(4);
    expect(table.rows[0].cells).toHaveLength(2);
    expect(table.textContent).toContain("거듭제곱의 뜻");
  });

  it("학생이 직접 채우는 이름·서명 표의 빈 열은 유지한다", () => {
    const source = `<table><tbody>
      <tr><th>이름</th><td>평가 내용</td><td></td><td></td></tr>
      <tr><th>서명</th><td>확인</td><td></td><td></td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.prunedTrailingColumnCount).toBe(0);
    expect(container.querySelector("table")!.rows[0].cells).toHaveLength(4);
  });

  it("독립된 값이 많은 표만 가로 보기 대상으로 표시한다", () => {
    const source = `<table><tbody>
      <tr><th>성취기준</th><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th></tr>
      <tr><td>[12대수01-01]</td><td>상</td><td>중상</td><td>중</td><td>중하</td><td>하</td></tr>
    </tbody></table>
    <table><tbody><tr><th>성취기준</th><td colspan="8">긴 설명</td></tr></tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;

    expect(result.wideTableCount).toBe(1);
    expect(container.querySelectorAll('table[data-source-wide-table="true"]')).toHaveLength(1);
  });

  it("짧은 결합 표도 명확한 표제어가 있으면 구획별로 나누어 빈 열을 정리한다", () => {
    const longStandards = "[12대수01-01] 거듭제곱과 거듭제곱근의 뜻과 성질을 설명하고 계산할 수 있다. ".repeat(5);
    const source = `<table><tbody>
      <tr><th>성취기준 및 성취기준별 성취수준</th><th>${longStandards}</th><th></th><th></th><th></th><th></th></tr>
      <tr><td>교과 역량</td><td>문제해결 능력과 추론 능력</td><td></td><td></td><td></td><td></td></tr>
      <tr><td>평가 시기</td><td>3월</td><td>반영비율</td><td>10%</td><td>영역만점</td><td>100점</td></tr>
      <tr><td>평가 방법</td><td>서술·논술</td><td></td><td></td><td></td><td></td></tr>
      <tr><td>평가 요소 및 채점 기준</td><td>개념을 이해하고 해결한다.</td><td></td><td></td><td></td><td></td></tr>
      <tr><td>유의점</td><td>사전에 안내한다.</td><td></td><td></td><td></td><td></td></tr>
    </tbody></table>`;
    const result = segmentSourceTables(source);
    const container = document.createElement("div");
    container.innerHTML = result.html;
    const sections = container.querySelectorAll(".sourceTableSection");

    expect(result.sectionCount).toBe(3);
    expect(sections[0].querySelector("table")!.rows[0].cells).toHaveLength(2);
    expect(result.prunedTrailingColumnCount).toBeGreaterThanOrEqual(4);
    expect(result.normalizedLongHeaderCellCount).toBe(1);
    expect(sections[0].querySelector('[data-source-long-header-cell="true"]')).not.toBeNull();
    expect(container.textContent).toContain("영역만점100점");
  });
});
