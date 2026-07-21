# Reconcile backlog

Seeded 2026-07-11 from FINDINGS.md (2026-06-09 review, verified against code at
seeding time) and WORKFLOW-HARDENING-PLAN.md. Entry format:
`[severity] summary — source · file:line pointer`.

## Open

- [low] Consent-gate ergonomics review (operator feedback 2026-07-20). Two symptoms:
  (a) the tracking issue stays open after a successful apply — the flow only posts an
  audit comment (`aviato/core/reconcile_flow.py:153` ff.) and even the later
  "drift resolved" pass refuses to close (`aviato/core/settings_drift_flow.py:141`),
  so a fully-applied issue like #47 lingers open with no resolved state;
  (b) the issue body hands the operator the exact
  `aviato reconcile . <issue> --confirm <diff_id>` command including the diff id
  (`aviato/core/settings_drift_flow.py:56`), so `--confirm` is copy-paste from the
  same artifact that carries the consent label and reads as ceremony rather than
  verification. Explore: auto-close (or an explicit resolved label) after a
  verified apply while keeping the no-unattended-close principle auditable; and
  either make the diff-id confirmation carry independent meaning (e.g. operator
  re-derives it) or drop the redundant prompt from the body. Constraint: keep the
  §5.8 fail-closed, diff-bound gate — this is UX, not a weakening. Distinct from
  the settled single-operator TOCTOU acceptance below; do not reopen that.

## Settled — do not reopen

- Single-operator consent TOCTOU is ACCEPTED (153fdfa) — the diff-bound `--confirm` gate is deliberately scoped to a single trusted operator; not re-filed.
