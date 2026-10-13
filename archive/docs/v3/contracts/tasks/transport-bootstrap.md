# Auto-G16 v3 tasks: transport-bootstrap

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:454-533 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V30-TRANSPORT-BOOTSTRAP-CHAIN-03

- **Outcome:** Close the implementation-review findings with one Transport-
  owned append-only SQLite `TransportStore`, durable remote workspace/artifact/
  job/receipt physical bindings, an explicit preinstalled bootstrap trust root,
  replacement-safe descriptor-relative remote operations, and deployment-
  manifest-bound executable invocation within the exact frozen threat model.
- **Scope:** Exact authority files only: `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`,
  `docs/v3/AUTONOMOUS_DEVELOPMENT.md`, and `docs/v3/STATUS.md`. No context-map,
  selector, product, or test mutation.
- **Failed evidence:** `798d3559d7c5ee6211a0b29977310f8adb871a5f`,
  `e49136e23c564cc9e0d9d97b905e43c45db73adc`, and
  `44db04180af8222c6e4619accfab0049e89bd3e0` remain immutable negative
  evidence; the last lacked closed per-operation response/binding schemas and
  one realizable fetch response channel.
- **Public shape:** Add only `TransportStore.create_new(path, *, approved_root)`,
  `TransportStore.open_existing(path, *, approved_root)`, and `close()`; add
  exact `transport_store_id` and `store_instance_id` bindings to Transport
  evidence; and require the same store in both RTwin adapter constructors and
  persisted job-binding replay. The effect adapter additionally receives the
  current public `ServerProfile` so manifest bytes have exactly one source and
  can close against each snapshot. Existing public Core/Approval/Workflow/
  Execution/Observe/Result/ScientificValidation/Review APIs and schemas remain
  unchanged.
- **Persistence:** Exact schema-v1 append-only store, deterministic UUIDv5
  identities, a one-time non-caller-selectable OS-CSPRNG nonce, exact logical
  store and physical-instance binding, idempotent replay, conflict fail-closed,
  descriptor-relative/no-follow root-parent-terminal handling, durable reopen,
  and no effect/retry/scientific authority. It detects clone/replacement within
  the frozen model; it does not claim uncloneability against malicious same-UID,
  root, kernel/filesystem, or deployment/bootstrap compromise.
- **Trust:** The exact canonical runtime content
  `transport-deployment-manifest-v1.json`, closed against the current resolved
  profile and snapshot, is final pre-start authority inside the frozen model.
  Its exact nine roots include both configured remote shells. `server_python`
  does not establish that trust; after deployment-trusted start it may detect
  drift and process only the fixed bootstrap source plus closed data packets.
  Caller source/module/operation upload, `eval`, `exec`, and arbitrary command
  execution are forbidden.
- **Safety:** Persist and reattest opaque workspace and artifact physical tokens
  descriptor-relatively/no-follow for every later effect/read. Freeze exact
  deployment-manifest evidence for every used executable, exact absolute-path
  structured execution, Windows first-hop parser/quoting, and POSIX single-token
  quoting when unavoidable. Descriptor execution and a new native wrapper are
  not required; strict prelaunch and practical postlaunch reattestation do not
  overclaim TOCTOU protection against excluded actors. Channels stay bounded
  through completion and EOF. Every operation uses one exact AGV3 request frame
  on stdin and one exact AGV3 response frame on stdout with an operation-specific
  closed binding/payload/result schema; stderr is capped diagnostic-only, and
  no unspecified binary/authority channel exists.
- **Command chain:** Freeze the real Mac OpenSSH -> Windows OpenSSH server ->
  declared `powershell-v1` or `cmd-v1` remote shell -> RTwin OpenSSH -> server
  OpenSSH -> `posix-sh-v1` -> `server_python` chain. Local `shell=False` removes
  only a local shell. `powershell-v1` has the exact file-attestation launcher;
  `cmd-v1` has exact quoting but fails deployment compatibility under this
  nine-root model because it has no trusted SHA-256 primitive. No grammar
  detection or fallback is permitted.
- **Reuse:** PORT/EXTRACT reviewed append-only SQLite, lexical no-follow,
  manifest, quoting, and stable-channel primitives; WRAP proven RTwin operation
  mechanics; REWRITE only store/physical-binding/data-protocol glue that legacy
  code couples to v2 governance or dynamic command behavior; DROP v2 authority,
  implicit retry/cleanup, self-attestation, and dynamic agent execution; DEFER
  a native wrapper, OpenSSH, deployment, credentials, and live work.
- **Explicit non-goals:** No Core/Execution store/API change, no alternate
  WINNER owner, no OpenSSH, deployment, credential/host-key policy, retry,
  qdel, deletion, cleanup, live RTwin/PBS/Gaussian, or V30-A live run.
- **Autonomy:** `OWNER-GUIDED` docs-only closeout. Once exact authority content
  is integrated after independent `0/0/0/0` review, the successor offline
  Transport implementation is gate-eligible; this document alone does not
  perform or authorize product/live mutation.
- **Acceptance:** Prove all conditions in
  `acceptance.md#v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain`,
  exact five-file scope, docs/anchor/static/diff/sensitive checks, and
  independent adversarial contract review.
- **Stop rules:** Stop for any existing upstream API/schema change, alternate
  trust root, dynamic remote code requirement, inability to persist/replay
  physical authority without retry, deployment/live requirement, sixth file,
  or unresolved P0/P1.
