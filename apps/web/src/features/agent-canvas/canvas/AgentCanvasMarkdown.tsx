import { Fragment, type ElementType, type ReactNode } from "react";

const HEADING_RE = /^(#{1,6})\s+(.*)$/;

function splitLines(value: string): string[] {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}

function hasMarkdownSignal(value: string): boolean {
  if (!value.trim()) {
    return false;
  }

  if (value.includes("```")) {
    return true;
  }

  return splitLines(value).some((line) => {
    const trimmed = line.trim();

    if (!trimmed) {
      return false;
    }

    if (HEADING_RE.test(trimmed)) {
      return true;
    }

    if (trimmed.startsWith("> ")) {
      return true;
    }

    if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      return true;
    }

    if (/\*\*[^ \n][^\n]*?\*\*/.test(trimmed)) {
      return true;
    }

    if (/__[^ \n][^\n]*?__/.test(trimmed)) {
      return true;
    }

    return /\[[^\]]+\]\([^)]+\)/.test(trimmed);
  });
}

function parseInline(source: string, keyBase: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^`\n]+?\*\*|__[^`\n]+?__|~~[^`\n]+?~~|\*[^`\n]+?\*|_[^`\n_]+_|\[[^\]]+\]\([^)\n]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(source)) !== null) {
    const token = match[0];
    const start = match.index;

    if (start > lastIndex) {
      parts.push(source.slice(lastIndex, start));
    }

    if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(<code key={`${keyBase}-inline-code-${parts.length}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(<strong key={`${keyBase}-inline-bold-${parts.length}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("__") && token.endsWith("__")) {
      parts.push(<strong key={`${keyBase}-inline-bold-${parts.length}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("~~") && token.endsWith("~~")) {
      parts.push(<s key={`${keyBase}-inline-strike-${parts.length}`}>{token.slice(2, -2)}</s>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(<em key={`${keyBase}-inline-em-${parts.length}`}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("_") && token.endsWith("_")) {
      parts.push(<em key={`${keyBase}-inline-em-${parts.length}`}>{token.slice(1, -1)}</em>);
    } else {
      const anchorMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (anchorMatch) {
        const href = anchorMatch[2];
        const safeHref = /^\s*(https?:\/\/|\/|#|\.\.?\/|mailto:|tel:)/i.test(href);
        parts.push(
          <a
            key={`${keyBase}-inline-link-${parts.length}`}
            href={safeHref ? href : "#"}
            target={safeHref ? "_blank" : undefined}
            rel={safeHref ? "noreferrer" : undefined}
            aria-label={safeHref ? undefined : "Unsafe link blocked"}
          >
            {anchorMatch[1]}
          </a>,
        );
      } else {
        parts.push(token);
      }
    }

    lastIndex = start + token.length;
  }

  if (lastIndex < source.length) {
    parts.push(source.slice(lastIndex));
  }

  return parts;
}

function parseMarkdownBlocks(source: string): ReactNode[] {
  const lines = splitLines(source);
  const blocks: ReactNode[] = [];
  let i = 0;
  let paragraphLines: string[] = [];

  const flushParagraph = () => {
    if (paragraphLines.length === 0) {
      return;
    }

    const text = paragraphLines.join("\n");
    const renderedLines = text.split("\n").map((line, lineIndex) => (
      <Fragment key={`paragraph-line-${blocks.length}-${lineIndex}`}>
        {parseInline(line, `paragraph-${blocks.length}-${lineIndex}`)}
        {lineIndex < text.split("\n").length - 1 ? <br /> : null}
      </Fragment>
    ));

    blocks.push(
      <p key={`paragraph-${blocks.length}`}>
        {renderedLines}
      </p>,
    );
    paragraphLines = [];
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flushParagraph();
      const fenceLang = trimmed.slice(3).trim();
      const fenceLines: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        fenceLines.push(lines[i]);
        i += 1;
      }
      blocks.push(
        <pre key={`code-${blocks.length}`}>
          <code className={fenceLang ? `language-${fenceLang}` : undefined}>
            {fenceLines.join("\n")}
          </code>
        </pre>,
      );
      if (i < lines.length) {
        i += 1;
      }
      continue;
    }

    const heading = HEADING_RE.exec(trimmed);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const title = heading[2];
      const Tag = `h${Math.min(level, 6)}` as ElementType;
      blocks.push(
        <Tag key={`heading-${blocks.length}`}>
          {parseInline(title, `heading-${blocks.length}`)}
        </Tag>,
      );
      i += 1;
      continue;
    }

    if (trimmed.startsWith("> ")) {
      flushParagraph();
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        quoteLines.push(lines[i].replace(/^>\s*/, ""));
        i += 1;
      }
      blocks.push(
        <blockquote key={`quote-${blocks.length}`}>
          {quoteLines.map((quoteLine, index) => (
            <p key={`quote-line-${blocks.length}-${index}`}>
              {parseInline(quoteLine, `quote-${blocks.length}-${index}`)}
            </p>
          ))}
        </blockquote>,
      );
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      flushParagraph();
      const listItems: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={`ul-item-${blocks.length}-${index}`}>
              {parseInline(item, `ul-item-${blocks.length}-${index}`)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      flushParagraph();
      const listItems: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={`ol-item-${blocks.length}-${index}`}>
              {parseInline(item, `ol-item-${blocks.length}-${index}`)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      i += 1;
      continue;
    }

    paragraphLines.push(line);
    i += 1;
  }

  flushParagraph();
  return blocks;
}

export function isLikelyMarkdown(source: string): boolean {
  return hasMarkdownSignal(source);
}

export function renderMarkdownAwareText(source: string): ReactNode[] {
  return parseMarkdownBlocks(source);
}
