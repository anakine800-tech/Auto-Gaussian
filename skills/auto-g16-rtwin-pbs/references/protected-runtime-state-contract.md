# Auto-G16 protected runtime/state successor

`auto-g16-protected-runtime-state-contract/1` is the additive, local-only
successor after PR4N.

- It accepts only an exact current owner-issued PR4N handoff.
- It stably reads the owner-selected runtime config and first-hop SSH config,
  recomputes the protected two-hop config binding, and binds normalized
  Windows root/project identities without publishing private path text.
- It keeps `/home/user100/SDL` fixed and exposes no remote-root override.
- It writes an append-only sibling journal, leaving the PR4L directory and
  every historical artifact unchanged.
- Its states are `ready`, `effect_not_started`,
  `effect_started_outcome_uncertain`, and `accepted_terminal`.
- One consumption performs the final `assert_current()`. The uncertain receipt
  must be durable before any future external effect. Recovery never retries an
  uncertain effect.
- Its reconciliation owner seals caller-acquired read-only evidence but does
  not obtain that evidence or connect to a remote system.

Schema validation is structural. Public validation adds portable semantic
checks. Exact owner replay and the non-copyable in-process seal are still
required to append a state transition.

This contract does not construct a legacy effect plan/raw owner, connect
`LegacyTransportAdapter`, invoke a runner, transfer, submit, query PBS, fetch,
cancel, clean up, delete, deploy, or grant live authority.
