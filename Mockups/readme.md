# Cerebro Design System

Cerebro is a personal knowledge vault — notes, sources, and AI-assisted retrieval organized as a linked graph. The visual language is neural/synaptic but restrained: a premium, technical tool for developers and knowledge workers, not a playful consumer app. No cartoon neurons, no gradient mesh backgrounds, no emoji.

This system was authored from a written brief (no attached codebase or Figma file) — colors, type families, spacing/radius ranges, and motion rules were specified directly; everything else (exact type scale, spacing/radius steps, component set, the danger red) was designed to fit.

## Visual foundations

**Color.** Near-black base (`--bg-base` #0A0A0F) with a slightly lifted elevated surface (`--bg-elevated` #13131A) for cards, inputs, and panels — no pure black borders anywhere; all borders are low-opacity white (8/12/18%). Violet (`--accent-primary` #8B5CF6) is the "something is alive" color: retrieval pulses, active/live nodes, primary buttons. It's used sparingly — most of the UI is neutral. Teal (`--accent-secondary` #2DD4BF) covers secondary actions and success states. Amber (`--accent-locked` #F59E0B) is reserved exclusively for encryption/lock UI (sealed notes, vault lock state, encrypted-field indicators) — never reuse it elsewhere, or the "locked" signal stops being trustworthy. Red (`--danger` #EF4444) was added for destructive actions (delete note, purge vault) since the brief didn't specify one; chosen to sit alongside the Tailwind-derived violet/teal/amber without competing with amber's reserved role.

**Type.** Inter for all UI text, JetBrains Mono for anything numeric or code-like — token counts, latency, chunk IDs, file sizes, hashes. The mono/sans split is a functional signal in this product: mono means "this value is exact and machine-produced," sans means "this is prose." Base UI size is 14px (dense, technical, not marketing-scale).

**Spacing & radius.** 4px base spacing scale (4 → 96px). Radius stays subtle everywhere (6/8/12px) — cards and panels never round past 12px. Full pill radius (999px) is reserved for badges and pill controls only; nothing else should look like a capsule.

**Motion.** Two easing modes, deliberately far apart. `--ease-soft` (220ms, standard cubic ease) is the default for panels, node hovers, card transitions — calm, physical, never bouncy. `--ease-pulse` (480ms, sharp deceleration) is reserved exclusively for the retrieval-pulse animation, so a sudden fast motion always reads as "a real retrieval/network event just happened," never as generic UI chrome. Don't borrow `--ease-pulse` for hover states or it loses that meaning.

**Iconography.** No icon set was provided or requested. Badges and status use color + text rather than icons. If icons are needed later, bring in a CDN set (e.g. Lucide) that matches the technical, geometric feel — flag it as a substitution when added.

## Components

Standard primitives, sized to what a knowledge-vault UI needs (no source defined the inventory, so a minimal set was authored rather than a full kit):

- **Button** — primary / secondary / ghost / danger, default/hover/active/disabled.
- **Input** — labeled text field, default/hover/focus/disabled, optional mono mode for code-like values.
- **Badge** — neutral / live / success / locked status pill, with an optional pulsing dot for "live."
- **Card** — elevated container for notes/nodes, optional mono `meta` line, optional interactive hover/active.

## Index

- `styles.css` — root stylesheet, imports everything below.
- `tokens/` — `colors.css`, `typography.css`, `spacing.css`, `radius.css`, `motion.css`.
- `components/button/`, `components/input/`, `components/badge/`, `components/card/` — one primitive per directory (`.jsx` + `.d.ts` + `.prompt.md` + a `.card.html` specimen).
- `guidelines/` — foundation specimen cards: color surfaces/accents/text, type (UI + mono), spacing, radius, motion.
- `SKILL.md` — portable skill file for using this system in Claude Code or elsewhere.

## Intentional additions

- **danger color** — not specified in the brief; added because the Button component needs a destructive variant. See Color above for the reasoning.
- **Card `meta` prop** — not asked for explicitly, but every card-like surface in a knowledge vault (notes, chunks, retrieval results) needs a compact metadata line, so it's built into the primitive rather than left to callers to restyle.
