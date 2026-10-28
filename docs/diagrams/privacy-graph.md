# Privacy layer: graph

## Current state (generated from the code with `make graph` in `backend/`)

```mermaid
graph TD;
	__start__([start]):::first
	inspect_report(inspect_report)
	strip_metadata(strip_metadata)
	sanitize_text(sanitize_text)
	__end__([end]):::last
	__start__ --> inspect_report;
	inspect_report --> strip_metadata;
	strip_metadata -. blocked .-> __end__;
	strip_metadata -. continue .-> sanitize_text;
	sanitize_text --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## Planned (hand-drawn, not yet built)

```mermaid
flowchart TD
  S([start]) --> A[strip_metadata]
  A --> B[sanitize_text]
  B --> C[sanitize_photos]
  C --> D[pseudonymize_user]
  D --> E[assemble]
  E --> F([end: SanitizedReport])
  A -. error .-> X[blocked_privacy]
  B -. error .-> X
  C -. error .-> X
  D -. error .-> X
  X --> G([end: operator decides])
```

Dotted arrows are the fail-closed branch: any failing step stops the report.
