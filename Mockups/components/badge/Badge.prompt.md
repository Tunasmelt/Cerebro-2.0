Small status label. `locked` (amber) is reserved exclusively for encryption/lock-related state — never use it for anything else, so amber stays a distinct signal in the interface. `live` with `dot` marks an actively-processing node using the same pulse timing as the retrieval-pulse animation.

```jsx
<Badge variant="live" dot>Retrieving</Badge>
<Badge variant="success">Indexed</Badge>
<Badge variant="locked">Sealed</Badge>
<Badge variant="neutral">Draft</Badge>
```
