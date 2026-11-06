import katex from "katex";

const INLINE_MATH = /\$([^$\n]+)\$/g;

export function normalizeExtractedTex(value: string) {
  return value
    .replace(/(?<!\\)\bover\b/g, "\\over")
    .replace(/\\left\s*\\\{\s*\{([^{}]+)\}\s*\\over\s*\{([^{}]+)\}/g, "\\left\\{\\frac{$1}{$2}")
    .replace(/\{([^{}]+)\}\s*\\over\s*\{([^{}]+)\}/g, "\\frac{$1}{$2}");
}

export default function MathText({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;

  for (const match of text.matchAll(INLINE_MATH)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(text.slice(cursor, index));

    const tex = normalizeExtractedTex(match[1]);
    const html = katex.renderToString(tex, {
      displayMode: false,
      throwOnError: false,
      strict: "ignore",
      trust: false,
      output: "htmlAndMathml",
    });
    parts.push(
      <span
        className="inlineMath"
        dangerouslySetInnerHTML={{ __html: html }}
        key={`${index}-${tex}`}
      />,
    );
    cursor = index + match[0].length;
  }

  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts.length ? parts : text}</>;
}
