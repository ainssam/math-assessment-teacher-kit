"use client";

import renderMathInElement from "katex/contrib/auto-render";
import { useEffect, useMemo, useRef, useState } from "react";

import { normalizeExtractedTex } from "./MathText";
import { segmentSourceTables } from "./lib/source-table-segmentation";

function normalizeExtractedMathNodes(root: HTMLElement) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => {
    node.data = node.data.replace(/\$([^$\n]+)\$/g, (_match, tex: string) => `$${normalizeExtractedTex(tex)}$`);
  });
}

export default function SourceDocumentHtml({ html }: { html: string }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [largeText, setLargeText] = useState(false);
  const [wideTables, setWideTables] = useState(false);
  const segmented = useMemo(() => segmentSourceTables(html), [html]);
  const hasTables = /<table\b/i.test(segmented.html);
  const transformed = (
    segmented.splitTableCount
    || segmented.mergedFragmentCount
    || segmented.reconstructedCellCount
    || segmented.orphanStandardGroupCount
    || segmented.recoveredNoteGroupCount
    || segmented.clampedRowspanCount
    || segmented.gradeContinuationRowCount
    || segmented.prunedTrailingColumnCount
    || segmented.normalizedLongHeaderCellCount
    || segmented.wideTableCount
  );
  useEffect(() => {
    if (!rootRef.current) return;
    normalizeExtractedMathNodes(rootRef.current);
    renderMathInElement(rootRef.current, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      throwOnError: false,
      strict: "ignore",
      trust: false,
    });
  }, [segmented.html]);

  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setExpanded(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [expanded]);

  return (
    <section
      className={`sourceDocumentViewer${expanded ? " isExpanded" : ""}${largeText ? " isLargeText" : ""}${wideTables ? " isWide" : ""}`}
      aria-label="원문 표 보기"
    >
      {hasTables ? (
        <div className="sourceDocumentToolbar" role="toolbar" aria-label="원문 표 표시 설정">
          <span>복잡한 표는 화면을 넓혀 확인할 수 있습니다.</span>
          <div>
            <button type="button" aria-pressed={wideTables} onClick={() => setWideTables((value) => !value)}>
              {wideTables ? "기본 표 폭" : "표 폭 넓게"}
            </button>
            <button type="button" aria-pressed={largeText} onClick={() => setLargeText((value) => !value)}>
              {largeText ? "기본 글자" : "글자 확대"}
            </button>
            <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
              {expanded ? "전체 화면 닫기" : "전체 화면"}
            </button>
          </div>
        </div>
      ) : null}
      <div
        ref={rootRef}
        className={`sourceDocumentHtml${transformed ? " sourceDocumentHtmlSegmented" : ""}`}
        data-source-table-sections={segmented.sectionCount || undefined}
        data-source-merged-fragments={segmented.mergedFragmentCount || undefined}
        data-source-reconstructed-cells={segmented.reconstructedCellCount || undefined}
        data-source-orphan-standard-groups={segmented.orphanStandardGroupCount || undefined}
        data-source-recovered-note-groups={segmented.recoveredNoteGroupCount || undefined}
        data-source-clamped-rowspans={segmented.clampedRowspanCount || undefined}
        data-source-grade-continuation-rows={segmented.gradeContinuationRowCount || undefined}
        data-source-pruned-trailing-columns={segmented.prunedTrailingColumnCount || undefined}
        data-source-normalized-long-header-cells={segmented.normalizedLongHeaderCellCount || undefined}
        data-source-wide-tables={segmented.wideTableCount || undefined}
        dangerouslySetInnerHTML={{ __html: segmented.html }}
      />
    </section>
  );
}
