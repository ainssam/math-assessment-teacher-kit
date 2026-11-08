"use client";

import renderMathInElement from "katex/contrib/auto-render";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";

import { normalizeExtractedTex } from "./MathText";
import { hidePreviewedTables, segmentSourceTables, sourceDisplayNeedsReview } from "./lib/source-table-segmentation";
import type { SourceTablePreview } from "./lib/catalog-api";

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

export default function SourceDocumentHtml({ html, previews = [], coveredTableKeys, coveredExcerpt = false }: { html: string; previews?: SourceTablePreview[]; coveredTableKeys?: string[]; coveredExcerpt?: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [largeText, setLargeText] = useState(false);
  const [wideTables, setWideTables] = useState(false);
  const previewKey = previews.map((preview) => preview.url).join("|");
  const [failedPreview, setFailedPreview] = useState<string>();
  const imageFailed = failedPreview === previewKey;
  const segmented = useMemo(() => {
    const result = segmentSourceTables(html);
    return !coveredExcerpt && !imageFailed && coveredTableKeys?.length
      ? { ...result, html: hidePreviewedTables(result.html, coveredTableKeys) }
      : result;
  }, [html, coveredTableKeys, coveredExcerpt, imageFailed]);
  const hasTables = /<table\b/i.test(segmented.html) || previews.length > 0;
  const needsReview = useMemo(() => !(previews.length && coveredExcerpt && !imageFailed) && sourceDisplayNeedsReview(segmented.html), [segmented.html, previews.length, coveredExcerpt, imageFailed]);
  const transformed = (
    segmented.splitTableCount
    || segmented.mergedFragmentCount
    || segmented.reconstructedCellCount
    || segmented.orphanStandardGroupCount
    || segmented.recoveredNoteGroupCount
    || segmented.clampedRowspanCount
    || segmented.clippedColspanCount
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

  const extracted = <div
    ref={rootRef}
    className={`sourceDocumentHtml${transformed ? " sourceDocumentHtmlSegmented" : ""}`}
    data-source-table-sections={segmented.sectionCount || undefined}
    data-source-merged-fragments={segmented.mergedFragmentCount || undefined}
    data-source-reconstructed-cells={segmented.reconstructedCellCount || undefined}
    data-source-orphan-standard-groups={segmented.orphanStandardGroupCount || undefined}
    data-source-recovered-note-groups={segmented.recoveredNoteGroupCount || undefined}
    data-source-clamped-rowspans={segmented.clampedRowspanCount || undefined}
    data-source-clipped-colspans={segmented.clippedColspanCount || undefined}
    data-source-grade-continuation-rows={segmented.gradeContinuationRowCount || undefined}
    data-source-pruned-trailing-columns={segmented.prunedTrailingColumnCount || undefined}
    data-source-normalized-long-header-cells={segmented.normalizedLongHeaderCellCount || undefined}
    data-source-wide-tables={segmented.wideTableCount || undefined}
    dangerouslySetInnerHTML={{ __html: segmented.html }}
  />;

  return (
    <section
      className={`sourceDocumentViewer${expanded ? " isExpanded" : ""}${largeText ? " isLargeText" : ""}${wideTables ? " isWide" : ""}`}
      aria-label="원문 표 보기"
    >
      {needsReview ? <p className="sourceExtractionNotice" role="status">일부 추출 문자나 병합 셀은 원문 대조가 필요합니다. 수식·배점은 학교알리미 원문에서 확인해 주세요.</p> : null}
      {hasTables ? (
        <div className="sourceDocumentToolbar" role="toolbar" aria-label="원문 표 표시 설정">
          <span>{previews.length ? "수식과 병합을 원문 표에서 확인할 수 있습니다." : "복잡한 표는 화면을 넓혀 확인할 수 있습니다."}</span>
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
      {previews.length ? <div className="sourceDocumentHtml sourceOriginalTables" data-source-original-table-count={previews.length}>
        {imageFailed ? <p role="status">원문 표를 불러오지 못했습니다. 추출 표와 학교알리미 원문을 함께 확인해 주세요.</p> : previews.map((preview, index) => <figure key={preview.url}>
          <Image className="sourceOriginalTableImage" src={preview.url} width={preview.width} height={preview.height}
            alt={preview.page_context ? `수행평가가 포함된 원문 ${preview.page}쪽` : `수행평가 원문 표 ${index + 1}, 원문 ${preview.page}쪽`} unoptimized
            onError={() => setFailedPreview(previewKey)} />
          <figcaption>{preview.rendered_from_hangul ? "한글 원문 렌더링" : "원문"} {preview.page}쪽{preview.page_context ? " · 같은 페이지의 다른 평가나 안내가 함께 보일 수 있습니다." : ` · 표 ${index + 1}`}</figcaption>
        </figure>)}
        {!coveredExcerpt ? extracted : <details className="sourceExtractedTables" open={imageFailed} data-source-extraction-fallback="true" data-source-complete-excerpt="true">
          <summary>추출 표 함께 보기</summary>
          <p>추출 표에는 수식이나 병합이 다르게 표시될 수 있습니다. 위 원문 표를 기준으로 확인해 주세요.</p>
          {extracted}
        </details>}
      </div> : extracted}
    </section>
  );
}
