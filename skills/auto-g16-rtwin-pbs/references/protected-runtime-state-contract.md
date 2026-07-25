# Auto-G16 protected runtime/state successor

`auto-g16-protected-runtime-state-contract/1` is the additive, local-only
successor after PR4N.

- It accepts only an exact current owner-issued PR4N handoff.
- Its own canonical module object, source origin, and issued classes remain
  identity-bound for seal, recovery, and `assert_current()`.
- Its exact adjacent PR4N module records the process's first canonical
  runtime/state owner; a later same-name execution cannot replace that
  registration, create a new journal, or recover the first owner's journal.
  Standard same-object reload is rejected before owner definitions or bindings
  can be replaced.
- It stably reads the owner-selected runtime config and first-hop SSH config,
  recomputes the protected two-hop config binding, and binds normalized
  Windows root/project identities without publishing private path text.
- It keeps `/home/user100/SDL` fixed and exposes no remote-root override.
- It writes an append-only sibling journal, leaving the PR4L directory and
  every historical artifact unchanged. Ready initialization publishes only a
  complete staged inode; explicit recovery may complete an absent/empty ready
  journal but never overwrites an invalid authority receipt.
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
The registration is a Python import-graph duplicate-load guard, not protection
from arbitrary code already running in the same interpreter.
