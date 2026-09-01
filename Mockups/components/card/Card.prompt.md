Elevated container for a note, source document, or graph node summary. Pass `meta` for code-like details (chunk ID, byte size, timestamp) — it renders in monospace. Set `interactive` when the card is clickable (e.g. a row in a note list).

```jsx
<Card title="Distributed systems reading list" meta="chk_a13f · 2.4kb · 3 links" interactive>
  Notes on consensus, CRDTs, and vector clocks.
</Card>
```
