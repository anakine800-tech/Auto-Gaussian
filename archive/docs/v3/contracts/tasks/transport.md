# Auto-G16 v3 tasks: transport

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:534-717 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`

- **Outcome:** Close the gap between snapshot-bound scheduler resources and the
  actual qsub invocation through one closed, deterministic, source-controlled
  dialect renderer.
- **Authority:** `OWNER-GUIDED`, followed by bounded autonomous implementation
  only after fresh independent contract review reaches `0/0/0/0`.
- **Contract scope:** `OWNER_DECISIONS.md`, `docs/v3/boundary-spec.md`,
  `docs/v3/acceptance.md`, this file, `docs/v3/STATUS.md`, and
  `config/context-map.toml` only.
- **Implementation scope:** Transport-owned bootstrap/driver/adapter code and
  `tests/v3/transport/**` only. No upstream public API/schema change.
- **Source authority:** Exact snapshot `ResolvedResourceRequest`; neither PBS
  bytes, Gaussian `%mem`/`%nprocshared`, caller argv, environment, profile
  defaults, scheduler defaults, nor legacy governance may replace it.
- **Dialect:** Fixed runtime content `pbs-resource-enactment-v1.json` selects a
  closed source renderer. The separate `V30-PBS-TORQUE-DIALECT-01` authority
  records the accepted read-only deployment evidence and exact production
  renderer. One explicitly synthetic renderer remains allowed offline and must
  be rejected before any live subprocess starts.
- **Protocol:** Successor bootstrap `/2`, table `/2`, and bootstrap-v2 source;
  same seven operations, framing, trust roots, caps, physical bindings,
  WINNER/REPLAY/UNKNOWN, and no-retry rules.
- **Validation:** Focused Transport, exact resource/dialect/request vectors,
  affected selector evidence once, synthetic composition deltas, and fresh
  independent adversarial review.
- **Reuse:** PORT resource/validation/no-shell primitives; EXTRACT neutral
  historical deployment facts only; WRAP RTwin/PBS mechanics; REWRITE the
  enactment seam because v3 currently omits resources and v2 governance is not
  authority; DROP caller/free-form/default and v2 authority; DEFER planner,
  telemetry, adaptive resources, multi-node policy, OpenSSH, qdel, and live.
- **Stop rules:** Stop for a required upstream public API/schema change, new
  retry/effect authority, production dialect guess, trust-model change, or live
  evidence required to choose semantics. Production qualification must come
  only from the separately accepted exact preflight evidence.
- **Non-goals:** No live RTwin/SSH/PBS/Gaussian, qsub/qstat, deployment,
  credentials, host-key acceptance, qdel/delete/cleanup, automatic retry,
  resource planning, or scientific interpretation.

### `V30-PBS-TORQUE-DIALECT-01`

- **Outcome:** Replace the production-dialect preflight blocker with one exact
  source-controlled Torque `6.1.0` single-node `nodes:ppn` renderer for the
  first V30-A deployment.
- **Authority:** Owner-approved two-phase lane: docs-only freeze and independent
  contract review first; only after normal integration may the bounded
  Transport implementation, focused/affected validation, independent review,
  and normal integration proceed autonomously.
- **Contract scope:** Exact authority files only: `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`, this file,
  `docs/v3/STATUS.md`, and `config/context-map.toml`.
- **Implementation scope:** Existing Transport-owned dialect/renderer/bootstrap
  boundary and `tests/v3/transport/**` only. No upstream public API/schema
  change.
- **Dialect:** Exact ID
  `auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`; exact argv is
  `-l`, one `nodes=1:ppn=C,mem=Mmb,walltime=W` value, `-q`, exact queue, then
  exact PBS basename. Integer MB and seconds replay without conversion.
- **Queue:** The first deployment requires exact `batch`; null or any other
  queue rejects. Observed scheduler defaults never become authority.
- **Executable evidence:** Manifest-only `server_qsub` is
  `/usr/local/bin/qsub`, 418920 bytes, SHA-256
  `f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d`;
  `server_qstat` is `/usr/local/bin/qstat`, 185656 bytes, SHA-256
  `3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a`.
  No package identity is invented.
- **Safety:** Synthetic remains non-live; production qualification alone grants
  no live effect. PBS resource directives remain forbidden, WINNER remains the
  sequencing gate, REPLAY is zero qsub, and UNKNOWN grants no retry.
- **Validation:** Exact three positive renderer vectors, closed negative matrix,
  qsub/qstat drift tests, affected synthetic composition delta, static/diff/
  sensitive checks, and fresh independent reviews at `0/0/0/0`.
- **Stop rules:** Stop for any upstream API/schema change, incompatible
  one-node/memory semantics, required extra scheduler resource/authority,
  changed qsub/qstat identity, or two failed same-class repairs.
- **Non-goals:** No generic PBS abstraction, multi-node policy, alternate
  queue, resource planner/telemetry, OpenSSH, deployment, live qsub/Gaussian,
  retry, qdel, deletion, or cleanup.

### `V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01`

- **Outcome:** Preserve the generic LF-rejecting POSIX token contract while
  giving only the exact attested fixed bootstrap one deterministic multiline
  single-argv quoting seam.
- **Authority:** Owner-guided maintenance through contract freeze, narrow
  implementation, focused/affected/synthetic validation, two independent
  reviews, normal integration, and exact-main closeout. Deployment is excluded.
- **Scope:** `auto_g16/transport/_bridge.py`, directly required Transport tests,
  and the minimum v3 authority/status documents. No upstream public API/schema.
- **Identity:** Successor launcher logical name is
  `auto-g16-v3-rtwin-launcher-v2.ps1`, 8576 bytes, 140 LF, SHA-256
  `1e6a8210...`; manifest schema/protocol v2 and the exact ten-root model
  remain. Bootstrap bytes remain exact 15562-byte
  `ad0ba2af...`; revision 4 binds the new launcher/manifest identities.
- **Validation:** Prove generic LF rejection, exact-bootstrap-only entry,
  strict UTF-8 byte roundtrip, one-word POSIX reconstruction, special-character
  literalness, Python 3.6 compile, unchanged inner length bound, focused and
  affected Transport, and synthetic V30-A composition.
- **Stop rules:** Stop for generic quoter weakening, bootstrap-byte or protocol
  change, manifest schema change, inner-bound overflow, upstream API/schema
  change, or two failed same-class repairs.
- **Non-goals:** No deployment, RTwin persistent write, workspace/staging,
  qsub/Gaussian, retry, qdel, cleanup, new Attempt, generic multiline shell, or
  caller-controlled execution surface.

### `V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01`

- **Outcome:** Replace the revision-4 launcher's EOF-dependent stdin copy with
  exact AGV3 header/length/payload acquisition before nested SSH, then exact
  write/flush/immediate nested-stdin close independent of outer EOF.
- **Authority:** Owner-guided maintenance through contract freeze, narrow
  product repair, focused/affected/composition validation, fresh independent
  adversarial review, normal integration, exact-main attestation, and revision-5
  deployment-packet preparation. Deployment and live qualification are excluded.
- **Scope:** `auto_g16/transport/_bridge.py`, directly required
  `tests/v3/transport/**`, and the minimum five v3 authority/status documents.
  No upstream public API/schema or selector change.
- **Identity:** Successor launcher is
  `auto-g16-v3-rtwin-launcher-v3.ps1`, 9579 bytes, 161 LF, SHA-256
  `7247beda...`; one successor manifest-v2 content instance and ServerProfile
  revision 5 bind the new launcher. Bootstrap/table/protocol `/2` and the exact
  ten-root inventory remain unchanged.
- **Safety:** No nested process exists until the complete capped frame is
  acquired. Bad magic, oversized length, or partial header/payload is zero
  nested connection. Bounded stdout/stderr drains and the one finite input
  write run concurrently after nested start; input completion closes nested
  stdin without duplex backpressure or outer-EOF dependence. The launcher never
  interprets AGV3 authority or reads beyond the declared frame. The bootstrap
  retains final EOF enforcement; Controller output remains exactly one frame.
- **Validation:** Prove open-outer-stdin completion and ordering; closed header
  negatives; full-length mutation forwarding/bootstrap rejection; unchanged
  quoting, attestation, Python 3.6, binary channel, REPLAY/UNKNOWN, qsub-once,
  Torque, and synthetic composition evidence; independent `0/0/0/0` review.
- **Residual process gate:** Before a future deployment/qualification, exact
  read-only reconciliation must prove prior residual count zero. Nonzero count
  requires a separate exact-process termination gate. No broad kill or cleanup.
- **Stop rules:** Stop for protocol/bootstrap semantics change, inability to
  acquire under the frozen cap, upstream public API/schema change, nested start
  before full frame, deployment/live requirement, or two failed same-class
  repairs.
- **Non-goals:** No deployment, nested real qualification, workspace/staging,
  qsub/Gaussian, retry, qdel, deletion/cleanup, recovery Attempt, OpenSSH, or
  generic transport redesign.

### `V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01`

- **Outcome:** Mechanically integrate the already-qualified Mac
  `/usr/bin/ssh` plus one RTwin `ProxyJump` route and freeze ServerProfile
  revision 8. Windows nested-stdin routes remain historical and are never an
  Option-1 fallback.
- **Reuse:** KEEP AGV3 framing/decoding, TransportStore, Core/effect semantics,
  bootstrap, resource/PBS authority, Observe/Result; WRAP the existing bounded
  subprocess supervisor; PORT exact Mac OpenSSH/config/trust/identity-reference
  mechanics; REPLACE only the profile-selected Windows nested command route.
- **Scope:** Private Transport bridge/driver helpers, focused Transport tests,
  and the minimum authority/status/context documents. No public API/schema,
  protocol, bootstrap, trust-root, or authority change.
- **Identity:** Bind `/usr/bin/ssh`, 1584576 bytes, SHA-256 `17542914...`, and
  final-key public fingerprint `SHA256:aqyVwyOa9wRiA93G52/rirqt/8ktUhUfX2Cja709w/s`.
  The exact public-key artifact and qualified private-file physical identity
  are profile-bound. Private keys remain local mode-0600 references whose bytes
  are never read. Both hops require `CertificateFile none`, closing implicit
  sibling user-certificate discovery.
- **Validation:** Focused Option-1 vectors, affected Transport/composition,
  static and sensitive-data audits, independent `0/0/0/0` review, Required CI,
  and CodeQL. Normal merge is authorized when exact-main compatibility passes.
- **Non-goals:** No deployment, new Attempt/approval/snapshot, workspace,
  qstat/qsub, Gaussian, qdel, cleanup, automatic retry, global SSH config
  mutation, agent forwarding, generic framework, or architecture exploration.

### V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01

- **Outcome:** Enact the exact snapshot-bound Attempt workspace as both qsub
  client cwd and scheduled Torque shell cwd, with named-path physical replay
  immediately before qsub.
- **Scope:** Private Transport renderer, fixed bootstrap, operation-table and
  runtime identities, focused/affected tests, minimum authority/status/context
  docs, and append-only future acquisition evidence closeout.
- **Preserve:** Existing `SUBMIT_QSUB_ONCE` request schema, AGV3 `/2`, ten-root
  trust model, public APIs, resource sole authority, at-most-once submission,
  `REPLAY` zero effect, and `UNKNOWN` no retry.
- **Stop:** Any public API/protocol/schema/trust change, live deployment,
  scheduler read, fetch, retry, cleanup, or new calculation Attempt.
