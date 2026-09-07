"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { parseAnswerSegments } from "@/lib/graph/citations";
import styles from "./AnswerMarkdown.module.css";

// Stage 7.10 — real markdown rendering for chat answers, shared by both
// render sites (/graph's live turn, /chat's replayed history) and the
// streaming-in-progress path. Previously every answer rendered as a
// plain-text <span> with only citation-marker parsing
// (lib/graph/citations.ts's parseAnswerSegments) — the system prompt
// asks Gemini not to echo raw markdown from source chunks, but that's
// a prompt-only mitigation.
//
// Post-launch fix: the first version of this component rewrote
// citation markers into a markdown link (`[cite](cite:<id>)`) and
// relied on ReactMarkdown's `a`-component override to intercept the
// `cite:` scheme and swap in a real chip button. Live in production
// this didn't reliably fire — the literal word "cite" showed up as
// plain link text, and clicking it did nothing useful (no real click
// handler was ever wired to that fallback anchor). Root cause aside,
// routing an internal click action through markdown link-destination
// parsing was the wrong layer for it to begin with: a citation chip
// is application UI, not something the document's own markdown should
// need to encode. Rewritten to render citation and text segments
// directly instead: `parseAnswerSegments` (unchanged, the same
// pre-7.10 splitter) breaks the raw text on `[[chunk:<id>]]` markers;
// each text segment renders through ReactMarkdown on its own, each
// citation segment renders as a real `<button>` with a real `onClick`,
// no markdown or URI-scheme indirection involved at all. `disallowed
// Elements={["p"]}`/`unwrapDisallowed` keeps each text segment's
// output inline (no stray block-level paragraph break) so segments
// still flow together the way the original single-block text did —
// the one real tradeoff versus the single-pass approach is that a
// citation landing *inside* a list/table would split that structure
// across segments, which is both rare (models cite at sentence
// boundaries, not mid-list-item) and a purely cosmetic degradation,
// not a broken or unclickable citation.

export type CitationRef = { chunk_id: string; document_id: string };

export interface AnswerMarkdownProps<C extends CitationRef> {
  text: string;
  citations: C[];
  citeChipClassName: string;
  onCiteClick: (citation: C, index: number) => void;
  citeChipTitle?: (citation: C, index: number) => string;
}

function CiteIcon() {
  // A small "quotation marks" glyph — the conventional citation symbol
  // — so a chip reads as "this is a citation" at a glance instead of
  // being just a bare number with no visual cue.
  return (
    <svg width="8" height="8" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M4.5 3C3.12 3 2 4.12 2 5.5S3.12 8 4.5 8c.17 0 .33-.02.5-.05C4.72 9.7 3.6 11 2 11v2c2.76 0 5-2.24 5-5V5.5C7 4.12 5.88 3 4.5 3zm7 0C10.12 3 9 4.12 9 5.5S10.12 8 11.5 8c.17 0 .33-.02.5-.05C11.72 9.7 10.6 11 9 11v2c2.76 0 5-2.24 5-5V5.5C14 4.12 12.88 3 11.5 3z" />
    </svg>
  );
}

export default function AnswerMarkdown<C extends CitationRef>({
  text,
  citations,
  citeChipClassName,
  onCiteClick,
  citeChipTitle,
}: AnswerMarkdownProps<C>) {
  const segments = parseAnswerSegments(text);

  return (
    <div className={styles.markdownBody}>
      {segments.map((segment, i) => {
        if (segment.type === "citation") {
          // A marker naming a chunk id outside the caller's own
          // resolved citations (hallucinated, server-dropped, or
          // every marker at all while streaming and citations isn't
          // known yet) renders nothing — same distrust-by-default
          // posture this had before Stage 7.10.
          const index = citations.findIndex((c) => c.chunk_id === segment.chunkId);
          if (index === -1) return null;
          const citation = citations[index];
          return (
            <button
              key={i}
              type="button"
              className={citeChipClassName}
              title={citeChipTitle ? citeChipTitle(citation, index) : undefined}
              onClick={() => onCiteClick(citation, index)}
            >
              <CiteIcon />
              {index + 1}
            </button>
          );
        }
        return (
          <ReactMarkdown
            key={i}
            remarkPlugins={[remarkGfm]}
            disallowedElements={["p"]}
            unwrapDisallowed
          >
            {segment.text}
          </ReactMarkdown>
        );
      })}
    </div>
  );
}
