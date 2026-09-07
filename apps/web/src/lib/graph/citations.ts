// Stage 1.7's prompt asks Gemini to cite using [[chunk:<real-id>]]
// markers; stream.py strips any marker naming a chunk outside the
// retrieved set before it ever becomes a `citation` event (see
// chat/stream.py's docstring). This module is the frontend half of
// that contract: it never trusts a marker on its own, only markers
// that also appear in the real `citation` events collected during the
// stream — matching the mockup's numbered cite-chip pattern in
// Mockups/ui_kits/chat/index.html instead of leaking the raw
// [[chunk:...]] syntax into the UI.
//
// Post-launch fix: this used to be /\[\[chunk:([^\]]+)\]\]/g — a
// single id, no `]` allowed inside. Live in production, Gemini
// sometimes cited more than one chunk for a claim as a single
// malformed group, e.g. [[chunk:id1], [chunk:id2]], instead of two
// separate well-formed markers as instructed (chat/prompt.py's
// SYSTEM_PROMPT_HEADER now says so explicitly). That group has no
// `]]` until its very end (ids never contain `]`), so `(.+?)\]\]` —
// non-greedy, any character — still spans it correctly where the old
// `[^\]]+` stopped dead at the first inner `]` and left the whole
// group as raw, unrendered text. Mirrors chat/prompt.py's
// `_CITATION_RE`/`_split_citation_ids` exactly — same widened regex,
// same split-on-malformed-connector logic — since both sides must
// recognize the identical marker syntax.
const CITATION_MARKER_RE = /\[\[chunk:(.+?)\]\]/g;
const CITATION_GROUP_SPLIT_RE = /\]\s*,\s*\[chunk:/;

function splitCitationIds(inner: string): string[] {
  return inner
    .split(CITATION_GROUP_SPLIT_RE)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

export type AnswerSegment =
  | { type: "text"; text: string }
  | { type: "citation"; chunkId: string };

/** Splits assistant answer text on [[chunk:<id>]] markers — including
 * the malformed multi-id group shape (see module docstring), which
 * yields one citation segment per real id inside it, back to back
 * with no text between them. Pure, no React or DOM — call after
 * streaming finishes, once the authoritative `citation` events are
 * all in. */
export function parseAnswerSegments(text: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(CITATION_MARKER_RE)) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, start) });
    }
    for (const chunkId of splitCitationIds(match[1])) {
      segments.push({ type: "citation", chunkId });
    }
    lastIndex = start + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }
  return segments;
}
