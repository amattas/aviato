# Aviato specifications

Specifications define Aviato's precise, testable behavior: process flows,
interfaces, schemas, state transitions, error handling, compatibility rules,
and plug-in contracts. Requirements define what must be true and why;
Architecture records the current structural solution; Security records threats,
mitigations, controls, assumptions, and residual risks.

Existing normative `§` headings are preserved verbatim because source code
cites them. `docs/requirements/README.md` remains the authoritative §-to-file
index and may resolve a requirement citation into a specification when the
numbered section is a behavioral contract.

```text
specifications/
├─ core/                  # cross-cutting behavioral contracts
└─ modules/<module>/      # process and plug-in behavior by capability
```

Specifications describe intended behavior, not implementation history. Open
work is tracked as [GitHub issues labeled `backlog`](https://github.com/amattas/aviato/issues?q=is%3Aissue+label%3Abacklog),
and settled "do not reopen" decisions live in a "Settled decisions — do not
reopen" section on each owning module's page; implementation and verification
status stays in `docs/requirements/traceability.md`.
