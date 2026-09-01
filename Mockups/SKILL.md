---
name: cerebro-design
description: Use this skill to generate well-branded interfaces and assets for Cerebro, a personal knowledge vault with a neural/synaptic visual theme — for production or throwaway prototypes/mocks. Contains color, type, spacing, radius, and motion tokens plus Button/Input/Badge/Card components.
user-invocable: true
---

Read README.md in this skill, and explore the other available files (tokens/, components/, guidelines/).

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, copy the token CSS and components and use them directly.

Key rules to keep in mind when designing with this system:
- Violet (`--accent-primary`) is used sparingly, only for live/active states and primary CTAs — it should not become the default color of everything.
- Amber (`--accent-locked`) is reserved exclusively for encryption/lock UI. Never use it for warnings, alerts, or anything else.
- Mono font (`--font-mono`) is for numeric/code-like values only (counts, latency, IDs, sizes), never for prose.
- `--ease-pulse` (fast, sharp) is reserved for the retrieval-pulse animation. Everything else eases with `--ease-soft` (calm, cubic, never bouncy).
- Corners stay subtle (6–12px). Full pill radius is for badges/pills only.

If the user invokes this skill without other guidance, ask what they want to build, ask a few questions, and act as an expert designer producing HTML artifacts or production code as needed.
