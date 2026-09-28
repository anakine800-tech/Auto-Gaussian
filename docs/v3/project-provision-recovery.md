# Auto-G16 Project creation-record recovery

## Task and authorization

Task: offline Project transport diagnostics and same-intent record recovery.
Owner instruction on 2026-09-28: “应离线定位传输证据缺口、补齐创建记录恢复入口”.
Base: `0babf19a72d53c417e04df147c1aca77004f45b1`; isolated branch
`codex/project-provision-recovery`. Primary class: feature development;
OWNER-GUIDED, non-BUS. Approved: offline implementation, focused/affected
validation and read-only independent review. The Owner subsequently authorized
commit, push, Draft PR creation and CI inspection for this exact repair. Merge
remains separately confirmed; applicable native evidence is required first.
Installation and remote effects remain behind their exact operational gates.
Scope: the existing Project journal/service, Project-only Transport diagnostics,
their existing bridge test module and this contract/handoff. Reuse OD-31,
[v31-shared](contracts/boundary/v31-shared.md#project-first-use-physical-provisioning)
and existing physical/schema validators. No public/Core schema, Attempt,
Transport operation, scientific input, qsub or UNKNOWN retry semantics change.
Default diagnostic budget: four repair cycles or 30 active minutes; record
validation and review at closeout. Preflight passed on the clean isolated base.

## Diagnosis and compatibility

`_wire_call` formerly discarded the driver's returned six values on ambiguous
completion. `_communicate_bounded` also discarded already captured prefixes on
failure. Project operations now retain capped diagnostic bytes, hashes, request
hash, transport status, return code and EOF flags. Their exception text excludes
raw output. Diagnostics are private, potentially sensitive and untrusted; the
operational caller must save them in private evidence, never public artifacts.
A timeout/cap/error prefix may be incomplete; false EOF/status remains a hard
failure. Legacy and non-Project driver behavior is unchanged. This cannot
reconstruct outputs that historical software already discarded, or establish
why the historical creation failed.

The old journal `/2` and default `create_new` retain their exact schema and
behavior. Explicit `create_new_recoverable` creates a fresh private `/3` journal;
there is no migration, replacement, alternate-location retry or silent upgrade.
The public physical-binding contract and original intent remain unchanged.

## Durable successful result and recovery

The existing owning Project attestor validates the complete successful response
and physical tokens. Only that normal creation path persists its result in a
new append-only `/3` table, after committed intent and before binding. The result
binds journal identity, exact intent ID/hash (including Project, resolved profile,
path, retained parent and runtime authority), parent and resulting Project
physical identity. Raw diagnostic bytes are never accepted as a success result.
The existing runtime authority identifies the profile, manifest and bootstrap;
local installed source qualification remains a separate deployment gate.
The durable result has committed readback before binding. Failed insertion,
commit/readback or malformed result stops; a later recovery never repeats mkdir.

`reconcile_remote_project` requires the exact existing intent ID and current
matching production authority. It performs one existing OBSERVE only. Outcomes:

- Existing durable binding and matching current physical identity: `BOUND`,
  return the original binding with no local/remote mutation.
- No durable success result (including all unbound `/2` historical intents):
  `UNKNOWN`, no binding, whether current observation is ABSENT or EXISTING.
- Durable `/3` success result and exact current parent/Project identity: finish
  only the missing local binding; subsequent reconciliation returns the same
  binding. A read-only journal reports `RECOVERABLE` without issuing a binding.
- Identity/authority/result conflict, disappearance or replacement: fail closed.

The caller explicitly chooses reconciliation; no scheduler, Controller or
exception handler invokes it automatically. It does not change Core state,
create another intent, accept an unbound directory, reset an old intent, or
create submission authority. Concurrent local completion may only converge to
the identical existing binding under the existing append-only conflict checks.

`open_existing_readonly` uses SQLite mode=ro plus immutable/query_only, rejects sidecars
and WAL headers before connecting, rechecks the initial file version and sidecars
on every attestation, verifies existing schema and physical/meta identity, and never
creates/migrates a journal. `inspect_intent` has no Transport dependency and
checks canonical payload, semantic ID and denormalized row columns. A live
OBSERVE through reconciliation remains a separately authorized operation.

## Historical anti limitation

The retained historical `/2` intent has no successful creation result. Its last
ABSENT observation cannot establish non-effect, create a result or permit a
retry. This change supplies safe record restoration/inspection but does not
unblock that real calculation. Resolving that history beyond UNKNOWN needs an
explicitly reviewed new disposition; an extra approval alone cannot supply
missing creation evidence. No historical journal or live state is changed here.

## Validation and integration boundary

Use existing bridge fixtures with process creation forbidden. Cover successful
result followed by binding-write failure and reopen, old/new unknown outcomes,
read-only byte preservation, wrong intent, parent/Project drift, ignored result
insert, raw transport and decode diagnostics, and unchanged existing flows.
Native process/filesystem behavior is integration-relevant under the handbook;
offline PASS alone does not qualify or deploy the new source. Any target evidence
requires a separately bounded authorization, never an implicit Gaussian retry.

## Offline closeout (2026-09-28)

- Initial clean `dev_preflight.py --require-clean --json`: PASS.
- Focused bridge: 71 tests PASS, including the 11 new recovery/diagnostic cases.
- Adjacent `tests.v3.transport`, `tests.v3.execution` and
  `tests.v31.transport.test_program_composition`: 303 tests PASS.
- `git diff --check`, static quality and local CI contract audit: PASS.
  This is not remote CI or branch-protection evidence.
- Independent read-only final review: P0=0, P1=0, P2=0, P3=0. The initial
  two P1 and two P2 findings were fixed and their failure cases checked.
- Two bounded implementation/review cycles, less than 30 active minutes;
  no repair-budget extension required. No remaining offline blocker.
- The candidate read-only entry inspected the retained original anti journal:
  version 2, exactly one existing intent, no binding or success result, and
  identical before/after database digest. Zero remote calls; original UNKNOWN
  disposition remains unchanged. Exact private evidence stays outside Git.

The source is an isolated integration candidate, not installed or remotely
qualified. New journal generation is opt-in; no running caller is silently
upgraded. Any target evidence and installation remain separately bound actions.
