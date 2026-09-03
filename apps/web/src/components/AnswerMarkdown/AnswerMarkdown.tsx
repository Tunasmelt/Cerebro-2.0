"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { prepareCitationMarkersForMarkdown } from "@/lib/graph/citations";
import styles from "./AnswerMarkdown.module.css";

// Stage 7.10 — a real markdown renderer for chat answers, shared by
// both render sites (/graph's live turn, /chat's replayed history) and
// the streaming-in-progress path. Previously every answer rendered as
// a plain-text <span> with only citation-marker parsing
// (lib/graph/citations.ts's parseAnswerSegments) — the system prompt
// asks Gemini not to echo raw markdown from source chunks, but that's
// a prompt-only mitigation: any slip-through, or a future less-
// compliant model, showed raw **/|/# characters to the user. This
// component and prepareCitationMarkersForMarkdown (citations.ts) close
// that gap for real: citation markers are rewritten into a `cite:`
// link ahead of parsing, then the `a` override below turns *only*
// that scheme into a real citation-chip button — every other link
// renders as an ordinary link, and everything else markdown produces
// (lists, emphasis, code, tables via remark-gfm) renders as intended
// instead of as literal clutter.

export type CitationRef = { chunk_id: string; document_id: string };

export interface AnswerMarkdownProps<C extends CitationRef> {
  text: string;
  citations: C[];
  citeChipClassName: string;
  onCiteClick: (citation: C, index: number) => void;
  citeChipTitle?: (citation: C, index: number) => string;
}

export default function AnswerMarkdown<C extends CitationRef>({
  text,
  citations,
  citeChipClassName,
  onCiteClick,
  citeChipTitle,
}: AnswerMarkdownProps<C>) {
  const prepared = prepareCitationMarkersForMarkdown(text, citations);

  const markdownComponents: Components = {
    a({ href, children }) {
      if (href?.startsWith("cite:")) {
        const chunkId = decodeURIComponent(href.slice("cite:".length));
        const index = citations.findIndex((c) => c.chunk_id === chunkId);
        if (index === -1) return null; // dropped marker, not a real citation
        const citation = citations[index];
        return (
          <button
            type="button"
            className={citeChipClassName}
            title={citeChipTitle ? citeChipTitle(citation, index) : undefined}
            onClick={() => onCiteClick(citation, index)}
          >
            {index + 1}
          </button>
        );
      }
      // An ordinary link the model actually wrote — real markdown, so
      // it should behave like one, not get swallowed by the citation
      // handling above.
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };

  return (
    <div className={styles.markdownBody}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
