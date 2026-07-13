# Requirements traceability

This seed-once matrix is the canonical requirement and threat evidence ledger.
Maintain it with the repo-local `traceability` skill; never reset an active
matrix from the starter template.

Allowed states: `proposed`, `accepted`, `implemented`, `verified`, `blocked`,
and `retired`.

- `implemented` requires implementation evidence.
- `verified` requires implementation and verification evidence.
- External gates remain `blocked` or explicitly outstanding until durable
  evidence exists.
- Use `—` only when a field is genuinely inapplicable, not when evidence is
  merely missing.

| ID | Source | State | Specification | Implementation evidence | Verification evidence | Notes |
|---|---|---|---|---|---|---|
