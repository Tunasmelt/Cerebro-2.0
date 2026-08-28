# Cerebro 2.0 — Claude Design Prompts

Each section below is self-contained — paste it directly into Claude Design.
Run the **Design System** prompt first; every other prompt assumes those
tokens exist and references them by name instead of restating raw hex
values, so the whole app stays visually consistent.

---

## 0. Design System & Tokens

```
Create a design system for "Cerebro" — a personal knowledge vault with a
neural/synaptic visual theme. This is a technical, premium product for
developers and knowledge workers, not a consumer toy — avoid anything
cartoonish or overly playful.

Palette:
- Background: near-black (#0A0A0F), a secondary elevated surface (#13131A)
- Primary accent: a bioluminescent violet (#8B5CF6) used sparingly for
  active/live states — retrieval pulses, active nodes, primary CTAs
- Secondary accent: a cool teal (#2DD4BF) for secondary actions and
  successful states
- Sealed/locked state: amber (#F59E0B) — reserve this color exclusively
  for encryption/lock-related UI so it reads as a distinct signal
- Text: off-white (#F4F4F5) primary, muted gray (#A1A1AA) secondary
- Borders: 1px, low-opacity white (8-12%), never harsh black lines

Typography: a technical sans (Inter or similar) for UI text, a monospace
(JetBrains Mono or similar) for anything numeric or code-like — token
counts, latency numbers, chunk IDs, file sizes.

Motion language: subtle, physics-based, never bouncy. Nodes and panels
ease with a soft cubic curve. Reserve fast, sharp motion exclusively for
the retrieval-pulse animation so it reads as "something real just
happened" against an otherwise calm interface.

Deliver: color tokens, type scale, spacing scale (4px base), border-radius
scale (subtle, 6-12px range, no pill shapes except pills/badges), and a
small component sheet showing button (primary/secondary/ghost/danger),
input, badge, and card in default/hover/active/disabled states.
```

---

## 1. Landing Page

```
Design a landing page for Cerebro, a personal knowledge vault that turns
documents and images into a searchable, visual "brain" you can query in
natural language. Audience: developers and technical knowledge workers
evaluating a personal tool, not enterprise buyers — tone is confident and
technical, not salesy.

Hero: a headline that leads with the retrieval + visualization angle (not
"AI-powered notes app" — that undersells it), a one-line subhead, a single
primary CTA ("Try it" / "Get started"), and a hero visual that is a live,
subtly animated preview of the brain graph itself — glowing document
nodes with faint connecting edges, one node pulsing as if just retrieved.
Do not use a generic stock illustration here; the graph IS the hero image.

Sections below the fold, in this order:
1. "Ask it anything you've stored" — a short chat exchange mockup showing
   a query and an answer with inline citations back to source documents.
2. "Watch it think" — a static frame of the graph mid-retrieval, with 2-3
   nodes highlighted and connected to a chat bubble, plus a one-line
   caption explaining these are the real documents that were retrieved,
   not a decorative animation.
3. "Lock what matters" — a compact visual of a sealed document card
   (amber lock badge) with copy clarifying it's passphrase-gated, not a
   vague "bank-level encryption" claim.
4. A three-column feature strip: Multimodal search, Real retrieval
   visualization, Session-scoped locked files.
5. Closing CTA band, same primary action as the hero.

Footer: minimal — product, docs link, GitHub, a small note on what data
protection actually means here (link out, don't explain inline).

Use the Cerebro design system tokens. Keep the page performant-looking —
no dense marketing clutter, generous whitespace, the graph visual should
feel like the most complex thing on the page.
```

---

## 2. Marketing — Features Page

```
Design a features page for Cerebro using the established design system.
Structure as alternating left/right image-and-text rows (not a flat grid
— this page should feel like a guided walkthrough), covering:

1. Multimodal ingest — documents and images in one searchable index,
   visual showing a PDF and a photo both flowing into the same graph node
   cluster.
2. Hybrid retrieval — a diagram-style visual (simple, not busy) showing
   vector search and full-text search merging into one ranked result,
   captioned "reciprocal rank fusion" for the technically curious without
   requiring the term to make sense on its own.
3. The brain graph — largest visual on the page, showing document
   clusters with a callout explaining cluster position reflects real
   embedding similarity, not decoration.
4. Sealed files — the passphrase-unlock interaction shown as a small
   before/after: locked card → passphrase prompt → unlocked with a
   session timer visible.
5. Full traceability — a screenshot-style mockup of an answer with every
   claim linked to its source chunk.

Each row: one concise headline, 2-3 sentences of body copy, no jargon
stacking. End the page with the same primary CTA as the landing page.
```

---

## 3. Marketing — Security & Privacy Page

```
Design a dedicated security/privacy page for Cerebro — this page's job is
to be the most *precise* page on the site, not the most reassuring one.
Structure it as two explicit columns under the heading "What this
protects against" and "What this does not protect against" — do not
soften or hide the second column, it is the credibility anchor of the
whole page.

Left column bullets (visually calm, teal accent):
- Files are stored encrypted at rest for sealed documents
- The decryption key is derived client-side from your passphrase and
  never stored
- Sealed content is excluded from semantic search until unlocked

Right column bullets (amber accent, same visual weight — not styled as
a warning box, styled as plain fact):
- The derived key is sent to the server per-request during an active
  unlock session, so this is not a zero-knowledge system
- Passphrase loss is unrecoverable by design — there is no reset flow
- Non-sealed documents are searchable by default; sealing is opt-in per
  file

Below the two columns: a simple horizontal flow diagram — Passphrase →
client-side key derivation (WebCrypto) → encrypted upload → decrypted
per-request during an active session — labeled plainly, no marketing
language on this diagram.

Tone throughout: technical documentation, not a trust badge page. No
padlock stock icons, no "military-grade" language.
```

---

## 4. Auth — Sign In / Sign Up

```
Design a sign-in and sign-up screen for Cerebro using the design system.
Centered card on the dark background, minimal chrome. Sign-up: email,
password, confirm password, single primary CTA, small link to sign-in.
Sign-in: email, password, "forgot password" link, primary CTA, small
link to sign-up. Support a secondary "Continue with GitHub" OAuth button
styled as a ghost button above a divider.

Include an error state (inline red-bordered field with a one-line message
below it, not a toast) and a loading state (button shows a small inline
spinner, label changes to "Signing in…", button disabled).

Do not include a "forgot passphrase" concept anywhere on this screen —
that only applies to sealed-file passphrases, a completely separate
concept from the account password, and conflating them in the UI would
be a real product bug.
```

---

## 5. App Shell & Navigation

```
Design the main authenticated app shell for Cerebro. Left sidebar
(collapsible, icon-only when collapsed): Brain (graph view, default
landing), Documents (library/upload), Chat (if not embedded in Brain
view), Kanban, Tasks, Playground, Settings — group Kanban/Tasks/
Playground visually as a secondary group below a divider, since they are
a later product tier and shouldn't compete visually with the core three.

Top bar: search-anything input (not the RAG chat — a fast fuzzy filter
across document titles), user avatar menu, and a small persistent status
indicator showing ingest job progress ("2 documents processing…") when
active, otherwise hidden entirely — it should not occupy space when idle.

Main content area is a single flexible canvas — the Brain view, Documents
view, etc. render inside it. Design the empty state for a brand-new
account: a calm, mostly-empty graph canvas with a single centered
"Upload your first document" prompt, not a wall of onboarding copy.
```

---

## 6. Brain Graph View

```
Design the core Brain graph screen for Cerebro. Full-canvas force-directed
graph of document nodes, colored by cluster, on the dark background —
nodes are small glowing circles, edges are faint low-opacity lines, only
visible on hover/selection to avoid visual noise at scale.

A persistent but unobtrusive chat input docks at the bottom center,
pill-shaped, floating over the canvas (not a fixed side panel — the graph
should feel like the primary surface).

Design the retrieval-pulse state explicitly: when a query is asked, show
2-4 nodes brightening with a soft glow animation, a transient bright edge
drawing from each retrieved node to the chat input, then fading over
roughly 2 seconds as the answer streams in. This state is the single most
important animation in the product — it must read as "these are the real
documents being used," not generic decoration.

Design a node's click-expanded state: clicking a document node opens a
compact side panel (not a modal — shouldn't block the graph) showing the
document title, type icon, a "view source" action, and its child chunk
nodes appearing as small satellites around the parent node.

Design a sealed node's distinct visual state: amber-tinted node with a
small lock glyph, dimmer than unlocked nodes, and its side panel shows
only metadata (title, type, size, date) plus a passphrase input instead
of content — reinforcing that sealed content is genuinely absent from
what's visible, not just visually hidden.

Include a minimal legend/key in a corner (small, dismissible) explaining
node color = cluster, brightness = recently retrieved.
```

---

## 7. Document Library & Upload

```
Design the Documents view for Cerebro — a list/grid toggle of all stored
documents with columns/fields: title, type icon, size, upload date,
status badge (processing / ready / failed / sealed), and a quick-action
menu (view, download original, seal/unseal, delete).

Design the upload flow as a drag-and-drop zone at the top of the view,
expanding to show a per-file progress row once files are dropped. Each
row shows filename, a slim progress bar, and a stage label that updates
through real states: "Uploading" → "Normalizing" → "Extracting" →
"Embedding" → "Ready" — this should read as genuine pipeline stages, not
a generic percentage bar, since it's showing the actual ingest job state.

Design the failed state for a row: red-accented, a one-line plain-English
error ("Couldn't read this PDF — it may be corrupted"), and a retry
action. Never show a raw stack trace or exception string in this UI.

Design the "seal this document" action as a small modal: passphrase
input, passphrase confirmation input, a clear one-line warning that this
cannot be recovered if forgotten (styled plainly, not as a scary red
alert — this is a fact, not danger-language), and a disabled confirm
button until both fields match.
```

---

## 8. Chat / Retrieval Panel

```
Design the chat interface for Cerebro (may be the same surface as the
Brain view's docked input, expanded, or a dedicated panel — design for
the expanded/focused state). User and assistant messages in a standard
chat layout, but assistant messages must show inline citation chips after
sentences or paragraphs that reference retrieved content — small numbered
badges that, on hover, show a preview card of the source chunk (document
title, snippet, page number if applicable) and on click, jump to that
document in the Brain view.

Design the streaming state: tokens appear progressively, and citation
chips appear only once fully resolved (not mid-stream as placeholders) to
avoid implying a source that turns out wrong.

Design an empty-context state: if a query returns no relevant documents,
the assistant message should say so plainly and suggest uploading
relevant content — never fabricate an answer, and the UI should make
"no sources found" visually distinct from a normal cited answer (e.g. no
citation rail, a small muted "no matching documents" tag instead).

Include a compact token/cost readout under the input (small monospace
text, muted) showing estimated tokens for the current draft query before
sending — this is a preview, distinct from the full Token Playground.
```

---

## 9. Kanban Board

```
Design a kanban board for Cerebro's task-management tier. Standard
column layout (default: Backlog, In Progress, Done, columns
user-configurable), cards showing title, optional short description,
optional linked-document chip (a card can reference a Cerebro document —
show as a small file-icon chip with truncated title), and a due-date
badge when set.

Design drag-and-drop states: a card mid-drag has a subtle lift shadow and
the target column highlights with a soft accent border. Design the
"add card" affordance as a minimal inline input at the bottom of each
column rather than a modal, to keep task entry fast.

Keep this screen visually quieter than the Brain view — no glow effects,
no neural theming — this is a utility surface, and should read as calm
and functional in contrast to the more atmospheric core product.
```

---

## 10. Todo List

```
Design a simple todo list view for Cerebro, separate from the kanban
board — a flat, linear list rather than a board, for quick personal
tasks. Each row: checkbox, task text, optional due date, optional
priority dot (low/medium/high, small colored dot not a loud badge).
Completed items move to a collapsed "Completed" section at the bottom
rather than disappearing, with a strikethrough style.

Design the add-task row as a persistent input pinned to the top of the
list, always visible, submitting on Enter. Keep this screen minimal —
same calm, utility tone as the kanban board, not neural-themed.
```

---

## 11. Token Playground

```
Design a token/prompt playground screen for Cerebro — a developer-facing
surface for inspecting and editing exactly what gets sent to the model.
Two-pane layout: left pane shows the assembled prompt broken into
labeled, editable sections (system instructions, retrieved context per
chunk, chat history, user query), each section collapsible and showing
its own token count in monospace. Right pane shows a live running total
(tokens, estimated cost, estimated latency) that updates as sections are
edited, plus a "Run" button to send the edited assembly and see the
model's response inline below.

Design each context-chunk section with its source citation visible
(document name, chunk id) so edits are traceable back to what was
actually retrieved. Design a "reset to original" action per section and
for the whole prompt.

Tone: dense, technical, monospace-forward — this screen is for a power
user debugging retrieval quality, not a general audience, and should not
share the calm/atmospheric styling of the Brain view.
```

---

## 12. Settings

```
Design a settings screen for Cerebro with a left sub-nav: Account,
Security, Data & Storage, API Usage. Account: email, password change,
delete-account (destructive, requires typed confirmation). Security:
a list of currently sealed documents with unseal/reseal actions and
active unlock-session indicators (which sessions are currently unlocked
and their remaining time, with a manual "lock now" action per session).
Data & Storage: a simple usage bar (used / limit) for both indexed and
original-file storage, shown as two distinct bars since they're separate
budgets, plus a per-document storage breakdown table. API Usage: a
simple table of embedding/generation calls this billing period with
cost, for cost transparency.

Keep destructive actions (delete account, reseal, revoke session)
visually distinct — a consistent danger-red only used for these, nowhere
else in the app, so its meaning stays reliable.
```
