<!-- Split from REQUIREMENTS.md (2026-07-11) - section numbering preserved verbatim. Index: docs/requirements/README.md -->

### 5.8 Authorization gate (reused by §5.7 and any settings mutation)

**Rule:** deny by default (§2.7). A reusable decision, not duplicated per call
site.

```mermaid
flowchart TD
    A["Settings mutation requested"] --> B{"Actor type = real human (User)?<br/>(unknown = no)"}
    B -- no --> D1["DENY"]
    B -- yes --> C{"Consent bound to the CURRENT diff?"}
    C -- "no / stale" --> D2["DENY (re-consent required)"]
    C -- yes --> E{"Role lookup succeeded?"}
    E -- no --> D3["DENY (lookup failure ≠ approval)"]
    E -- yes --> F{"Role authorized (admin)?"}
    F -- no --> D4["DENY"]
    F -- yes --> G["ALLOW"]
```
