export type SegmentedSourceHtml = {
  html: string;
  splitTableCount: number;
  sectionCount: number;
  mergedFragmentCount: number;
  reconstructedCellCount: number;
  orphanStandardGroupCount: number;
  recoveredNoteGroupCount: number;
  clampedRowspanCount: number;
  clippedColspanCount: number;
  gradeContinuationRowCount: number;
  prunedTrailingColumnCount: number;
  normalizedLongHeaderCellCount: number;
  wideTableCount: number;
};

type SectionKey = "overview" | "standards" | "method" | "rubric";

/** Report remaining visible extraction faults without guessing missing values. */
export function sourceDisplayNeedsReview(value: string) {
  if (typeof DOMParser === "undefined") return false;
  const document = new DOMParser().parseFromString(value, "text/html");
  for (const fallback of document.querySelectorAll('details[data-source-extraction-fallback]')) fallback.remove();
  if (/[\ue000-\uf8ff\ufffd]|\bgfedcb?\b/u.test(document.body.textContent || "")) return true;
  for (const table of document.querySelectorAll("table")) {
    const rows = Array.from(table.rows);
    const grid: boolean[][] = rows.map(() => []);
    for (const [r, row] of rows.entries()) {
      let c = 0;
      for (const cell of Array.from(row.cells)) {
        while (grid[r][c]) c += 1;
        for (let rr = r; rr < Math.min(rows.length, r + cell.rowSpan); rr += 1) {
          for (let cc = c; cc < c + cell.colSpan; cc += 1) {
            if (grid[rr][cc]) return true;
            grid[rr][cc] = true;
          }
        }
        c += cell.colSpan;
      }
    }
  }
  return false;
}

export function sourceTableKey(text: string) {
  let hash = BigInt("14695981039346656037");
  const mask = BigInt("18446744073709551615");
  for (const char of text.normalize("NFKC").replace(/\s+/g, "")) {
    hash = ((hash ^ BigInt(char.codePointAt(0)!)) * BigInt("1099511628211")) & mask;
  }
  return hash.toString(16).padStart(16, "0");
}

/** Keep unmatched source content visible; only collapse tables covered by crops. */
export function hidePreviewedTables(value: string, keys: string[]) {
  if (typeof DOMParser === "undefined" || !keys.length) return value;
  const document = new DOMParser().parseFromString(value, "text/html");
  const covered = new Set(keys);
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (table.parentElement?.closest("table") || !covered.has(sourceTableKey(table.textContent || ""))) continue;
    const details = document.createElement("details");
    details.className = "sourceExtractedTables";
    details.setAttribute("data-source-extraction-fallback", "true");
    details.setAttribute("data-source-covered-key", sourceTableKey(table.textContent || ""));
    const summary = document.createElement("summary");
    summary.textContent = "대응하는 추출 표 함께 보기";
    const note = document.createElement("p");
    note.textContent = "수식과 병합은 위 원문 표를 기준으로 확인해 주세요.";
    table.before(details);
    details.append(summary, note, table);
  }
  return document.body.innerHTML;
}

type SectionRange = {
  key: SectionKey;
  start: number;
  end: number;
};

type CellPlacement = {
  cell: HTMLTableCellElement;
  rowStart: number;
  rowEnd: number;
  columnStart: number;
  columnSpan: number;
};

const SECTION_META: Record<SectionKey, { label: string; rank: number }> = {
  overview: { label: "평가 개요·수행과제", rank: 0 },
  standards: { label: "성취기준·성취수준", rank: 1 },
  method: { label: "평가 방법·운영", rank: 2 },
  rubric: { label: "채점 기준·배점", rank: 3 },
};

function compact(value: string) {
  return value.replace(/\s+/g, "").replace(/[·･ㆍ:：]/g, "");
}

function rowSection(row: HTMLTableRowElement): SectionKey | null {
  const cells = Array.from(row.cells).map((cell) => compact(cell.textContent || ""));
  const leading = cells.filter(Boolean).slice(0, 3);
  const first = leading[0] || "";
  const early = leading.join(" ");
  const all = cells.join(" ");

  if (/(?:^| )(평가영역명|수행과제|평가과제|과제명)/.test(early)) return "overview";
  if (/성취기준/.test(early) || /성취기준별성취수준/.test(early)) return "standards";
  if (/(?:^| )평가(방법|방식|유형|시기)/.test(early)) return "method";
  if (
    /^(평가요소|채점기준|세부평가기준|수행수준)/.test(first)
    || (/평가요소/.test(all) && /(수행수준|채점기준)/.test(all) && /(배점|척도)/.test(all))
  ) return "rubric";
  return null;
}

function inferredInitialSection(rows: HTMLTableRowElement[]): SectionKey {
  const explicit = rowSection(rows[0]);
  if (explicit) return explicit;
  const sample = compact(rows.slice(0, 8).map((row) => row.textContent || "").join(" "));
  if (/\[(?:10|12)[A-Za-z가-힣ⅠⅡ\d]{1,20}[-‐‑‒–—]?\d{2}[-‐‑‒–—]\d{2}\]/u.test(sample)) return "standards";
  if (/(?:^|[^A-Za-z])A(?:[^A-Za-z]|$)/.test(sample) && /수있다/.test(sample)) return "standards";
  if (/평가요소|채점기준|수행수준|배점/.test(sample)) return "rubric";
  return "overview";
}

function rowCellSignature(row: HTMLTableRowElement) {
  return Array.from(row.cells)
    .map((cell) => `${cell.tagName}:${cell.colSpan}:${compact(cell.textContent || "")}`)
    .join("|");
}

function knownRepeatedHeader(row: HTMLTableRowElement) {
  const text = compact(row.textContent || "");
  return (
    (/성취기준/.test(text) && /(평가기준|성취수준)/.test(text))
    || (/평가요소/.test(text) && /(채점기준|수행수준|배점)/.test(text))
  );
}

/**
 * PDF converters sometimes emit every page of one table as a separate table,
 * repeating an identical header row.  Merge only directly adjacent fragments
 * whose header cells and spans are exactly identical.
 */
function mergeRepeatedHeaderTables(document: Document) {
  let mergedFragmentCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (!table.isConnected || table.rows.length < 2) continue;
    const header = table.rows[0];
    if (!knownRepeatedHeader(header)) continue;
    const signature = rowCellSignature(header);
    let tableMerged = false;
    let next = table.nextElementSibling;
    while (next instanceof HTMLTableElement && next.rows.length >= 2) {
      const nextHeader = next.rows[0];
      if (!knownRepeatedHeader(nextHeader) || rowCellSignature(nextHeader) !== signature) break;
      const body = table.tBodies.item(table.tBodies.length - 1) || table.createTBody();
      for (const row of Array.from(next.rows).slice(1)) {
        body.append(row.cloneNode(true));
      }
      const following = next.nextElementSibling;
      next.remove();
      next = following;
      mergedFragmentCount += 1;
      tableMerged = true;
    }
    if (tableMerged) table.setAttribute("data-source-merged-fragments", "true");
  }
  return mergedFragmentCount;
}

function rowGrade(row: HTMLTableRowElement) {
  const grades = Array.from(row.cells)
    .map((cell) => compact(cell.textContent || ""))
    .filter((value) => /^[A-E]$/.test(value));
  return grades.length === 1 ? grades[0] : null;
}

function visibleRowWidth(row: HTMLTableRowElement) {
  return Array.from(row.cells).reduce((total, cell) => total + Math.max(1, cell.colSpan), 0);
}

function withoutLeadingBlankPlaceholders(
  row: HTMLTableRowElement,
  maximumWidth: number,
) {
  while (
    visibleRowWidth(row) > maximumWidth
    && row.cells.length > 1
    && !compact(row.cells[0].textContent || "")
  ) {
    row.cells[0].remove();
    row.setAttribute("data-source-leading-placeholder-removed", "true");
  }
}

/**
 * A page break can leave A-C achievement levels at the bottom of one table
 * and D-E at the top of the next.  Join only that exact A,B,C -> D,E sequence.
 * Empty leading cells in the new page are converter placeholders for rowspans
 * that began on the previous page, so they are removed from the cloned rows.
 */
function mergeAchievementLevelContinuations(document: Document) {
  let mergedRowCount = 0;
  const tables = Array.from(document.body.querySelectorAll("table"));
  for (const [tableIndex, table] of tables.entries()) {
    if (!table.isConnected || table.rows.length < 3) continue;
    const previousRows = Array.from(table.rows);
    const previousGrades = previousRows.map(rowGrade).filter((grade) => grade !== null);
    if (previousGrades.slice(-3).join("") !== "ABC") continue;
    const next = tables.slice(tableIndex + 1).find((candidate) => candidate.isConnected);
    if (!(next instanceof HTMLTableElement) || next.rows.length < 2) continue;
    const nextRows = Array.from(next.rows);
    const nextGradeEntries = nextRows
      .map((row, rowIndex) => ({ grade: rowGrade(row), rowIndex }))
      .filter((entry) => entry.grade !== null);
    if (
      nextGradeEntries.length < 2
      || nextGradeEntries[0].rowIndex > 4
      || `${nextGradeEntries[0].grade}${nextGradeEntries[1].grade}` !== "DE"
    ) continue;
    const secondGradeIndex = nextGradeEntries[1].rowIndex;
    const evidence = compact(`${table.textContent || ""} ${next.textContent || ""}`);
    const hasAchievementEvidence = (
      /(성취기준|성취수준|수준진술문|\[(?:10|12)[A-Za-z가-힣ⅠⅡ])/u.test(evidence)
      && /(수있|수준|뜻을안|이해|작성)/.test(evidence)
    );
    const hasRubricEvidence = (
      /(평가요소|수행수준|채점기준|배점)/.test(evidence)
      && /(점수|점|기준|수준)/.test(evidence)
    );
    if (!hasAchievementEvidence && !hasRubricEvidence) continue;

    let continuationEnd = secondGradeIndex + 1;
    while (continuationEnd < nextRows.length) {
      const row = nextRows[continuationEnd];
      if (rowGrade(row) || rowSection(row)) break;
      const text = compact(row.textContent || "");
      if (/^(평가방법|평가요소|평가유형|교과역량|채점|기본점수|미제출|장기)/.test(text)) break;
      continuationEnd += 1;
    }

    const body = table.tBodies.item(table.tBodies.length - 1) || table.createTBody();
    const maximumWidth = visibleRowWidth(previousRows.at(-1)!);
    for (const sourceRow of nextRows.slice(0, continuationEnd)) {
      const row = sourceRow.cloneNode(true) as HTMLTableRowElement;
      withoutLeadingBlankPlaceholders(row, maximumWidth);
      if (rowGrade(row)) {
        row.setAttribute("data-source-grade-continuation", "true");
        mergedRowCount += 1;
      } else {
        row.setAttribute("data-source-page-continuation", "true");
      }
      body.append(row);
      sourceRow.remove();
    }
    table.setAttribute("data-source-merged-grade-continuation", "true");
    if (!next.rows.length) {
      const scroll = next.parentElement?.classList.contains("sourceTableScroll")
        ? next.parentElement
        : null;
      const section = scroll?.parentElement?.classList.contains("sourceTableSection")
        ? scroll.parentElement
        : null;
      const wrapper = section?.parentElement?.classList.contains("sourceTableSections")
        ? section.parentElement
        : null;
      if (section) section.remove();
      else next.remove();
      if (wrapper && !wrapper.querySelector("table")) wrapper.remove();
    }
  }
  return mergedRowCount;
}

function lastNonEmptyCell(row: HTMLTableRowElement) {
  return Array.from(row.cells).reverse().find((cell) => compact(cell.textContent || ""));
}

function shortGapElements(table: HTMLTableElement) {
  const gap: Element[] = [];
  let previous = table.previousElementSibling;
  while (
    previous
    && !(previous instanceof HTMLTableElement)
    && /^H[2-6]$/.test(previous.tagName)
    && compact(previous.textContent || "").length <= 32
  ) {
    gap.unshift(previous);
    previous = previous.previousElementSibling;
  }
  return { previousTable: previous instanceof HTMLTableElement ? previous : null, gap };
}

/**
 * Repair the narrow continuation fragment visible when a PDF page split sends
 * only the final words of several rubric cells to a second mostly-empty table.
 * The repair is accepted only when row counts match a unique consecutive run
 * of visibly unfinished cells in the preceding table.
 */
function mergeSuffixContinuationTables(document: Document) {
  let reconstructedCellCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    if (!table.isConnected || table.rows.length < 4 || table.rows.length > 24) continue;
    const [blankHeader, ...suffixRows] = Array.from(table.rows);
    if (Array.from(blankHeader.cells).some((cell) => compact(cell.textContent || ""))) continue;
    const suffixCells = suffixRows.map((row) => {
      const nonEmpty = Array.from(row.cells).filter((cell) => compact(cell.textContent || ""));
      return nonEmpty.length === 1 ? nonEmpty[0] : null;
    });
    if (suffixCells.some((cell) => !cell)) continue;
    const suffixTexts = suffixCells.map((cell) => compact(cell?.textContent || ""));
    if (suffixTexts.some((text) => !text || text.length > 32)) continue;

    const { previousTable, gap } = shortGapElements(table);
    if (!previousTable) continue;
    const previousRows = Array.from(previousTable.rows);
    const matchingRuns: HTMLTableCellElement[][] = [];
    for (let start = 0; start + suffixRows.length <= previousRows.length; start += 1) {
      const cells = previousRows.slice(start, start + suffixRows.length).map(lastNonEmptyCell);
      if (
        cells.every(Boolean)
        && cells.every((cell) => /(?:기준을|충족하지|수준을|이상을|미만)$/.test(compact(cell?.textContent || "")))
      ) {
        matchingRuns.push(cells as HTMLTableCellElement[]);
      }
    }
    if (matchingRuns.length !== 1) continue;

    for (const [index, target] of matchingRuns[0].entries()) {
      target.append(document.createTextNode(` ${suffixCells[index]!.textContent || ""}`));
      target.setAttribute("data-source-reconstructed-cell", "true");
      reconstructedCellCount += 1;
    }

    if (gap.length) {
      const note = document.createElement("aside");
      note.className = "sourceRecoveredFragmentNotes";
      const label = document.createElement("strong");
      label.textContent = "원문 변환 중 표 밖에 남은 문구";
      note.append(label);
      for (const element of gap) {
        const span = document.createElement("span");
        span.textContent = element.textContent || "";
        note.append(span);
        element.remove();
      }
      previousTable.after(note);
    }
    table.remove();
  }
  return reconstructedCellCount;
}

const ORPHAN_STANDARD_RE = /^\s*(?:\[\s*(?:10|12)[A-Za-z가-힣ⅠⅡ\d]{1,20}\s*[-‐‑‒–—]?\s*\d{2}\s*[-‐‑‒–—]\s*\d{2}\s*\]\s*)+$/u;

function groupOrphanAchievementStandards(document: Document) {
  let groupCount = 0;
  const children = Array.from(document.body.children);
  let index = 0;
  while (index < children.length) {
    const current = children[index];
    if (!ORPHAN_STANDARD_RE.test(current.textContent || "") || current.querySelector("table")) {
      index += 1;
      continue;
    }
    const run: Element[] = [];
    while (
      index < children.length
      && ORPHAN_STANDARD_RE.test(children[index].textContent || "")
      && !children[index].querySelector("table")
    ) {
      run.push(children[index]);
      index += 1;
    }
    if (run.length < 2) continue;
    const section = document.createElement("aside");
    section.className = "sourceOrphanStandards";
    const heading = document.createElement("strong");
    heading.textContent = "원문에 별도 표기된 성취기준";
    section.append(heading);
    for (const element of run) {
      const code = document.createElement("span");
      code.textContent = element.textContent || "";
      section.append(code);
      element.remove();
    }
    const anchor = children[index] || null;
    document.body.insertBefore(section, anchor);
    groupCount += 1;
  }
  return groupCount;
}

function groupShortDisplacedHeadings(document: Document) {
  let groupCount = 0;
  const children = Array.from(document.body.children);
  let index = 0;
  while (index < children.length) {
    const current = children[index];
    const isShortHeading = (
      /^H[4-6]$/.test(current.tagName)
      && compact(current.textContent || "").length > 0
      && compact(current.textContent || "").length <= 32
    );
    if (!isShortHeading) {
      index += 1;
      continue;
    }
    const run: Element[] = [];
    while (
      index < children.length
      && /^H[4-6]$/.test(children[index].tagName)
      && compact(children[index].textContent || "").length > 0
      && compact(children[index].textContent || "").length <= 32
    ) {
      run.push(children[index]);
      index += 1;
    }
    if (run.length < 2) continue;
    const note = document.createElement("aside");
    note.className = "sourceRecoveredFragmentNotes";
    const label = document.createElement("strong");
    label.textContent = "원문 변환 중 표 밖에 남은 문구";
    note.append(label);
    for (const element of run) {
      const span = document.createElement("span");
      span.textContent = element.textContent || "";
      note.append(span);
      element.remove();
    }
    const anchor = children[index] || null;
    document.body.insertBefore(note, anchor);
    groupCount += 1;
  }
  return groupCount;
}

function clampOverflowingRowspans(document: Document) {
  let clampedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    for (const [rowIndex, row] of rows.entries()) {
      const maximum = rows.length - rowIndex;
      for (const cell of Array.from(row.cells)) {
        const raw = Number.parseInt(cell.getAttribute("rowspan") || "1", 10);
        if (!Number.isFinite(raw) || raw <= maximum) continue;
        if (maximum > 1) cell.setAttribute("rowspan", String(maximum));
        else cell.removeAttribute("rowspan");
        cell.setAttribute("data-source-rowspan-clamped", "true");
        clampedCount += 1;
      }
    }
  }
  return clampedCount;
}

/**
 * Old PDF grids sometimes extend the last content cell into a blank vertical
 * spacer already occupied by a rowspan. Original PDF comparisons confirm that
 * both cells end at the spacer boundary. Clip only this empty trailing overlap;
 * never move, truncate, or overwrite another populated cell.
 */
function clipBlankSpacerOverlaps(document: Document) {
  let clippedCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    const occupied: (HTMLTableCellElement | undefined)[][] = rows.map(() => []);
    for (const [rowIndex, row] of rows.entries()) {
      let column = 0;
      const cells = Array.from(row.cells);
      for (const [cellIndex, cell] of cells.entries()) {
        while (occupied[rowIndex][column]) column += 1;
        let span = Math.max(1, cell.colSpan);
        const collisions = Array.from({ length: span }, (_, offset) => ({
          offset, active: occupied[rowIndex][column + offset],
        })).filter((entry) => entry.active);
        const first = collisions[0]?.offset;
        const trailingCell = cells.slice(cellIndex + 1).every((next) => !compact(next.textContent || ""));
        if (first && trailingCell && collisions.every((entry) => !compact(entry.active!.textContent || ""))
          && Array.from({ length: span - first }, (_, offset) => occupied[rowIndex][column + first + offset]).every(Boolean)) {
          span = first;
          if (span > 1) cell.setAttribute("colspan", String(span));
          else cell.removeAttribute("colspan");
          cell.setAttribute("data-source-colspan-clipped", "true");
          clippedCount += 1;
        }
        for (let r = rowIndex; r < Math.min(rows.length, rowIndex + Math.max(1, cell.rowSpan)); r += 1) {
          for (let c = column; c < column + span; c += 1) {
            occupied[r][c] ||= cell;
          }
        }
        column += span;
      }
    }
  }
  return clippedCount;
}

function sectionRanges(rows: HTMLTableRowElement[]): SectionRange[] {
  let currentKey: SectionKey = inferredInitialSection(rows);
  const sections: SectionRange[] = [{ key: currentKey, start: 0, end: rows.length }];

  for (const [rowIndex, row] of rows.entries()) {
    const candidate = rowSection(row);
    const beginsNewCycle = (
      candidate === "overview"
      || (currentKey === "rubric" && candidate === "standards")
    );
    if (
      candidate
      && candidate !== currentKey
      && (beginsNewCycle || SECTION_META[candidate].rank > SECTION_META[currentKey].rank)
    ) {
      sections.at(-1)!.end = rowIndex;
      currentKey = candidate;
      sections.push({ key: currentKey, start: rowIndex, end: rows.length });
    }
  }
  return sections;
}

function positiveSpan(value: string | null, maximum: number) {
  const parsed = Number.parseInt(value || "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, maximum) : 1;
}

function tableCellPlacements(rows: HTMLTableRowElement[]): CellPlacement[] {
  const occupied: boolean[][] = Array.from({ length: rows.length }, () => []);
  const placements: CellPlacement[] = [];

  for (const [rowIndex, row] of rows.entries()) {
    let columnIndex = 0;
    for (const cell of Array.from(row.cells)) {
      while (occupied[rowIndex][columnIndex]) columnIndex += 1;
      const rowSpan = positiveSpan(cell.getAttribute("rowspan"), rows.length - rowIndex);
      const columnSpan = positiveSpan(cell.getAttribute("colspan"), 50);
      const placement = {
        cell,
        rowStart: rowIndex,
        rowEnd: rowIndex + rowSpan,
        columnStart: columnIndex,
        columnSpan,
      };
      placements.push(placement);
      for (let targetRow = placement.rowStart; targetRow < placement.rowEnd; targetRow += 1) {
        for (
          let targetColumn = placement.columnStart;
          targetColumn < placement.columnStart + placement.columnSpan;
          targetColumn += 1
        ) {
          occupied[targetRow][targetColumn] = true;
        }
      }
      columnIndex += columnSpan;
    }
  }
  return placements;
}

function trimColgroup(table: HTMLTableElement, keepWidth: number) {
  for (const group of Array.from(table.querySelectorAll(":scope > colgroup"))) {
    let columnIndex = 0;
    for (const column of Array.from(group.querySelectorAll(":scope > col"))) {
      const span = positiveSpan(column.getAttribute("span"), 50);
      if (columnIndex >= keepWidth) {
        column.remove();
      } else if (columnIndex + span > keepWidth) {
        const retained = keepWidth - columnIndex;
        if (retained > 1) column.setAttribute("span", String(retained));
        else column.removeAttribute("span");
      }
      columnIndex += span;
    }
    if (!group.children.length) group.remove();
  }
}

/** Remove only columns that are empty in every row of the rendered table. */
function pruneTrailingBlankColumns(document: Document) {
  let prunedColumnCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    if (!rows.length) continue;
    const tableText = compact(table.textContent || "");
    if (/(학번|학생번호|이름|서명|확인자)/.test(tableText)) continue;
    const placements = tableCellPlacements(rows);
    const width = placements.reduce(
      (maximum, placement) => Math.max(maximum, placement.columnStart + placement.columnSpan),
      0,
    );
    if (width < 4) continue;
    const used = Array.from({ length: width }, () => false);
    for (const placement of placements) {
      if (!compact(placement.cell.textContent || "")) continue;
      for (
        let column = placement.columnStart;
        column < placement.columnStart + placement.columnSpan;
        column += 1
      ) used[column] = true;
    }
    const lastUsed = used.lastIndexOf(true);
    const keepWidth = lastUsed + 1;
    const trailing = width - keepWidth;
    if (keepWidth < 2 || trailing < 2 || (rows.length <= 2 && tableText.length < 120)) continue;

    for (const placement of placements) {
      const end = placement.columnStart + placement.columnSpan;
      if (placement.columnStart >= keepWidth) {
        placement.cell.remove();
      } else if (end > keepWidth) {
        const retained = keepWidth - placement.columnStart;
        if (retained > 1) placement.cell.setAttribute("colspan", String(retained));
        else placement.cell.removeAttribute("colspan");
      }
    }
    trimColgroup(table, keepWidth);
    table.setAttribute("data-source-pruned-trailing-columns", String(trailing));
    prunedColumnCount += trailing;
  }
  return prunedColumnCount;
}

function markLongHeaderCells(document: Document) {
  let normalizedCount = 0;
  for (const cell of Array.from(document.body.querySelectorAll("th"))) {
    const text = compact(cell.textContent || "");
    if (
      text.length < 180
      || !(/\[(?:10|12)[A-Za-z가-힣ⅠⅡ]/u.test(text) || cell.querySelectorAll("br").length >= 3)
    ) continue;
    cell.setAttribute("data-source-long-header-cell", "true");
    normalizedCount += 1;
  }
  return normalizedCount;
}

/**
 * Keep genuinely multi-column source tables readable by opting them into the
 * document viewer's horizontal table mode.  A large colspan alone is not
 * enough: the row must contain at least five independently populated cells,
 * so a two-column label/value table with converter padding remains compact.
 */
function markWideTables(document: Document) {
  let wideTableCount = 0;
  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const hasPopulatedWideRow = Array.from(table.rows).some((row) => {
      const cells = Array.from(row.cells);
      const populatedCellCount = cells.filter((cell) => compact(cell.textContent || "")).length;
      return visibleRowWidth(row) >= 6 && populatedCellCount >= 5;
    });
    if (!hasPopulatedWideRow) continue;
    table.setAttribute("data-source-wide-table", "true");
    wideTableCount += 1;
  }
  return wideTableCount;
}

function sectionBody(
  document: Document,
  rows: HTMLTableRowElement[],
  placements: CellPlacement[],
  section: SectionRange,
) {
  const body = document.createElement("tbody");
  for (let rowIndex = section.start; rowIndex < section.end; rowIndex += 1) {
    const targetRow = rows[rowIndex].cloneNode(false) as HTMLTableRowElement;
    const startingCells = placements
      .filter((placement) => (
        Math.max(placement.rowStart, section.start) === rowIndex
        && placement.rowStart < section.end
        && placement.rowEnd > section.start
      ))
      .sort((left, right) => left.columnStart - right.columnStart);

    for (const placement of startingCells) {
      const cell = placement.cell.cloneNode(true) as HTMLTableCellElement;
      const visibleStart = Math.max(placement.rowStart, section.start);
      const visibleEnd = Math.min(placement.rowEnd, section.end);
      const visibleRowSpan = visibleEnd - visibleStart;
      if (visibleRowSpan > 1) cell.setAttribute("rowspan", String(visibleRowSpan));
      else cell.removeAttribute("rowspan");
      if (placement.rowStart < section.start) {
        cell.setAttribute("data-source-rowspan-continuation", "true");
      }
      targetRow.append(cell);
    }
    body.append(targetRow);
  }
  return body;
}

/**
 * Split only long source tables whose own row labels expose clear sections.
 * Cell text and rowspan/colspan values are preserved; this is a presentation
 * repair and never rewrites the archived source or invents a boundary.
 */
export function segmentSourceTables(value: string): SegmentedSourceHtml {
  if (typeof DOMParser === "undefined" || !value.trim()) {
    return {
      html: value,
      splitTableCount: 0,
      sectionCount: 0,
      mergedFragmentCount: 0,
      reconstructedCellCount: 0,
      orphanStandardGroupCount: 0,
      recoveredNoteGroupCount: 0,
      clampedRowspanCount: 0,
      clippedColspanCount: 0,
      gradeContinuationRowCount: 0,
      prunedTrailingColumnCount: 0,
      normalizedLongHeaderCellCount: 0,
      wideTableCount: 0,
    };
  }

  const document = new DOMParser().parseFromString(value, "text/html");
  const clippedColspanCount = clipBlankSpacerOverlaps(document);
  const reconstructedCellCount = mergeSuffixContinuationTables(document);
  let gradeContinuationRowCount = mergeAchievementLevelContinuations(document);
  const mergedFragmentCount = mergeRepeatedHeaderTables(document);
  const orphanStandardGroupCount = groupOrphanAchievementStandards(document);
  const recoveredNoteGroupCount = groupShortDisplacedHeadings(document);
  const clampedRowspanCount = clampOverflowingRowspans(document);
  let splitTableCount = 0;
  let sectionCount = 0;

  for (const table of Array.from(document.body.querySelectorAll("table"))) {
    const rows = Array.from(table.rows);
    if (rows.length < 5) continue;
    const sections = sectionRanges(rows);
    if (sections.length < 2) continue;
    const placements = tableCellPlacements(rows);

    const wrapper = document.createElement("div");
    wrapper.className = "sourceTableSections";
    wrapper.setAttribute("role", "group");
    wrapper.setAttribute("aria-label", "원문 표 구획");

    for (const [index, section] of sections.entries()) {
      const sectionElement = document.createElement("section");
      sectionElement.className = "sourceTableSection";

      const heading = document.createElement("h3");
      heading.textContent = SECTION_META[section.key].label;
      sectionElement.append(heading);

      const scroll = document.createElement("div");
      scroll.className = "sourceTableScroll";
      const sectionTable = table.cloneNode(false) as HTMLTableElement;
      sectionTable.removeAttribute("id");
      sectionTable.setAttribute("aria-label", SECTION_META[section.key].label);
      sectionTable.append(sectionBody(document, rows, placements, section));
      scroll.append(sectionTable);
      sectionElement.append(scroll);
      wrapper.append(sectionElement);

      if (index === 0) {
        const caption = table.querySelector(":scope > caption");
        if (caption) sectionTable.prepend(caption.cloneNode(true));
      }
    }

    table.replaceWith(wrapper);
    splitTableCount += 1;
    sectionCount += sections.length;
  }
  // Section splitting can expose a page-break continuation that was embedded
  // in one converter table. Repair that newly adjacent A-C / D-E pair too.
  gradeContinuationRowCount += mergeAchievementLevelContinuations(document);
  const prunedTrailingColumnCount = pruneTrailingBlankColumns(document);
  const normalizedLongHeaderCellCount = markLongHeaderCells(document);
  const wideTableCount = markWideTables(document);

  return {
    html: document.body.innerHTML,
    splitTableCount,
    sectionCount,
    mergedFragmentCount,
    reconstructedCellCount,
    orphanStandardGroupCount,
    recoveredNoteGroupCount,
    clampedRowspanCount,
    clippedColspanCount,
    gradeContinuationRowCount,
    prunedTrailingColumnCount,
    normalizedLongHeaderCellCount,
    wideTableCount,
  };
}
