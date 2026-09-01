// Stage 1.7's prompt asks Gemini to cite using [[chunk:<real-id>]]
// markers; stream.py strips any marker naming a chunk outside the
// retrieved set before it ever becomes a `citation` event (see
// chat/stream.py's docstring). This module is the frontend half of
// that contract: it never trusts a marker on its own, only markers
// that also appear in the real `citation` events collected during the
// stream — matching the mockup's numbered cite-chip pattern in
// Mockups/ui_kits/chat/index.html instead of leaking the raw
// [[chunk:...]] syntax into the UI.
const CITATION_MARKER_RE = /\[\[chunk:([^\]]+)\]\]/g;

export type AnswerSegment =
  | { type: "text"; text: string }
  | { type: "citation"; chunkId: string };

/** Splits assistant answer text on [[chunk:<id>]] markers. Pure, no
 * React or DOM — call after streaming finishes, once the authoritative
 * `citation` events are all in. */
export function parseAnswerSegments(text: string): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(CITATION_MARKER_RE)) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, start) });
    }
    segments.push({ type: "citation", chunkId: match[1] });
    lastIndex = start + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }
  return segments;
}

/** Strips markers entirely — used while a response is still streaming.
 * `citation` events (the only thing that tells us a marker is real, not
 * dropped) arrive only after the full token stream completes per
 * stream.py's ordering, so a marker visible mid-stream can't yet be
 * resolved into a chip; showing the raw bracket syntax in the meantime
 * would be worse than briefly hiding it. */
export function stripCitationMarkers(text: string): string {
  return text.replace(CITATION_MARKER_RE, "");
}
