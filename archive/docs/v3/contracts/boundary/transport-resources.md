# Auto-G16 v3 boundary: transport-resources

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [Canonical transport evidence identity](transport-composition.md#canonical-transport-evidence-identity)
- [Historical bootstrap /1 canonical deployment-manifest vector](transport-bootstrap-v1.md#historical-bootstrap-1-canonical-deployment-manifest-vector)
- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03 Physical and Bootstrap Authority Closeout](transport-bootstrap.md#v30-transport-bootstrap-chain-03-physical-and-bootstrap-authority-closeout)

<!-- Moved from docs/v3/boundary-spec.md:3004-3186 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### Snapshot-derived PBS resource enactment

`ExecutionSnapshot.resolved_resource_request` is the sole scheduler-resource
authority. Transport derives a private `ResourceEnactment` mechanical value
with exactly `execution_snapshot_id`, `resolved_resource_request_id`, `cores`,
`memory_mb`, `walltime_seconds`, `queue`, and `scheduler_dialect_id`. The first
six values replay the identity-closed snapshot exactly; the dialect is selected
only by current-profile runtime content named
`pbs-resource-enactment-v1.json`. The canonical descriptor is UTF-8 canonical
JSON plus one LF with exactly `schema` and `dialect`, where `schema` is
`auto-g16-v3-pbs-resource-enactment/1`. It contains no resource value,
executable, argv, option, format string, shell text, or credential.

`SUBMIT_QSUB_ONCE` protocol `/2` carries only the exact PBS basename and the
closed nested resource-enactment object. It carries no rendered argv. The fixed
Transport adapter validates that value against the current identity-closed
snapshot/profile before framing. The fixed bootstrap validates exact key sets,
types, IDs, positive non-boolean integer
resources, optional portable queue, and a closed dialect identifier. A
source-controlled renderer then derives qsub argv solely from dialect, cores,
memory MB, walltime seconds, optional queue, and PBS basename; the exact
manifest-bound qsub executable is invoked with `shell=False`. Any mismatch,
unknown/missing dialect, unrepresentable walltime, queue substitution, extra
token, or caller-supplied argv rejects before qsub.
The bootstrap neither reconstructs nor independently authenticates an
ExecutionSnapshot; equality with snapshot authority is owned by the adapter
before the bounded request crosses the transport boundary.

The one offline dialect is exactly
`auto-g16-v3-pbs-resource-enactment/synthetic-test/1`. It is deliberately not
a scheduler dialect and renders the exact non-production vector
`(--auto-g16-synthetic-cores, <cores>, --auto-g16-synthetic-memory-mb,
<memory_mb>, --auto-g16-synthetic-walltime-seconds, <walltime_seconds>,
[--auto-g16-synthetic-queue, <queue>], <pbs_basename>)`. The live subprocess
driver and fixed bootstrap reject execution of this dialect before process/qsub
creation. Its pure renderer is test evidence only. It proves deterministic
binding without guessing PBS Pro, Torque, OpenPBS, or deployment syntax.

### Exact Torque 6.1.0 production dialect

The accepted read-only deployment preflight qualifies exactly one production
renderer for the first V30-A target:
`auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`. It is not a
generic Torque/PBS renderer. Its deployment evidence is the exact active
single-node Torque `6.1.0` server with `np = 44`, queue `batch`, and these
manifest-owned executable roots:

| root | exact path | size | SHA-256 |
| --- | --- | ---: | --- |
| `server_qsub` | `/usr/local/bin/qsub` | 418920 | `f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d` |
| `server_qstat` | `/usr/local/bin/qstat` | 185656 | `3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a` |

The binaries are not package-manager-owned. Their manifest identity therefore
does not invent a package name or version authority. The production renderer
returns arguments only; the manifest-bound `server_qsub.path` remains the sole
executable selection at `run_exact(...)`.

For positive non-boolean integers `C = cores`, `M = memory_mb`, and
`W = walltime_seconds`, exact queue `Q`, and portable PBS basename `B`, the
complete production argument tuple is exactly:

```text
("-l", "nodes=1:ppn=C,mem=Mmb,walltime=W", "-q", "Q", "B")
```

The integers use canonical decimal digits with no sign. Resources are one
comma-separated `-l` value in the exact order `nodes`, `mem`, `walltime`.
Memory stays integer MB and time stays integer seconds. No GB conversion,
`HH:MM:SS` conversion, split `-l`, alternative spelling, option reordering, or
caller fragment is valid.

For the first V30-A deployment, queue is mandatory and must equal `batch`.
`queue = null` and every other token reject before process creation. The
observed default queue is never used as resource authority. Active PBS
resource directives, including `#PBS -l` and `#PBS -q`, remain rejected by the
staged v3 template contract, so qsub arguments are the only scheduler-resource
enactment.

The descriptor schema remains unchanged and closed. It admits only the exact
synthetic-test ID and this exact Torque ID. There is no submit-time detection,
fallback, alias, version range, executable, argv fragment, or scheduler
default in the descriptor. The Torque dialect is mechanically live-capable;
the synthetic dialect remains non-live. Neither classification grants an
effect: the complete live authority chain and a separate V30-A Live Owner Gate
remain required.

For the synthetic test dialect, `queue = null` emits no synthetic queue pair.
For the production Torque dialect, queue is required and must equal `batch`;
there is no default or omission path. An explicit queue is never replaced.
Walltime uses integer seconds without floating point or rounding. Memory comes
from exact `memory_mb`, never Gaussian `%mem`; cores come from exact `cores`,
never `%nprocshared`. PBS template resource directives remain forbidden.
Descriptor drift changes the resolved profile and snapshot and therefore
requires new exact Operational Confirmation. `REPLAY` performs zero qsub and
`UNKNOWN` never authorizes a second qsub.

Because request and operation-table semantics change, the successor identities
are `auto-g16-v3-rtwin-bootstrap/2`,
`auto-g16-rtwin-operation-table/2`, and
`auto-g16-v3-rtwin-bootstrap-v2.py`. Protocol `/1` and its exact vectors remain
immutable historical evidence. Protocol `/2` keeps the same seven operations,
AGV3 framing, bounded channels, nine deployment trust roots, physical
bindings, no-shell execution, and no-retry semantics. The v2 table changes
only the submit row's declared argv authority to the exact ordered inputs
`scheduler_dialect_id`, `cores`, `memory_mb`, `walltime_seconds`, `queue`, and
`pbs_basename`; final argv is renderer output, never request data.

The exact synthetic descriptor bytes are
`{"dialect":"auto-g16-v3-pbs-resource-enactment/synthetic-test/1","schema":"auto-g16-v3-pbs-resource-enactment/1"}\n`:
114 bytes with SHA-256
`9327ef2f0e11f5292daa7af22c00276bc504e2ffb31c2fdb585642fec1cd462c`.
The exact canonical table-v2 bytes are 1570 bytes with SHA-256
`14cdd511bb6c4eb78af8f07d774cfdae27fc1c661dae8692b45e48ccd7fa31af`.
They equal the historical table object except `version` is `/2` and submit
`argv_template` is exactly
`["{scheduler_dialect_id}","{cores}","{memory_mb}","{walltime_seconds}","{queue}","{pbs_basename}"]`.
For submit only, those markers declare closed renderer inputs rather than
caller/final argv. All other table rows and fields replay byte-for-byte.

For protocol `/2`, the exact `SUBMIT_QSUB_ONCE` binding keys remain the `/1`
submitted set: `transport_store_id`, `store_instance_id`,
`runtime_attestation_id`, `attempt_id`, `execution_snapshot_id`,
`submission_intent_id`, `remote_workspace`, `workspace_authority_id`,
`workspace_physical_token_base64`,
`prepared_input_artifact_authority_id`,
`prepared_input_artifact_physical_token_base64`,
`pbs_template_artifact_authority_id`, and
`pbs_template_artifact_physical_token_base64`. Its payload has exactly two
keys: `pbs_basename` and `resource_enactment`. The nested object has exactly
seven keys: `execution_snapshot_id`, `resolved_resource_request_id`, `cores`,
`memory_mb`, `walltime_seconds`, `queue`, and `scheduler_dialect_id`.
Nested `execution_snapshot_id` equals the binding value; the request/resource
ID and four resource values equal the current snapshot. All IDs and dialect
are non-empty closed strings, cores/memory/walltime are positive non-boolean
integers, and queue alone may be JSON `null`; otherwise it is one portable
name. Extra, missing, bool-as-int, alias, or mismatched values reject.

The exact canonical `/2` qsub request vector is 958 bytes with SHA-256
`73c94b0942724b8627016de958bcea247098a5b68b47a3baf0f8c0b9dd8253ad`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","pbs_template_artifact_authority_id":"pbs-artifact-1","pbs_template_artifact_physical_token_base64":"cGJzLXRva2VuLTE=","prepared_input_artifact_authority_id":"input-artifact-1","prepared_input_artifact_physical_token_base64":"aW5wdXQtdG9rZW4tMQ==","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"runtime-1","store_instance_id":"instance-1","submission_intent_id":"intent-1","transport_store_id":"store-1","workspace_authority_id":"workspace-1","workspace_physical_token_base64":"d29ya3NwYWNlLTE="},"operation":"SUBMIT_QSUB_ONCE","payload":{"pbs_basename":"job.pbs","resource_enactment":{"cores":8,"execution_snapshot_id":"snapshot-1","memory_mb":12288,"queue":"simple","resolved_resource_request_id":"resource-request-1","scheduler_dialect_id":"auto-g16-v3-pbs-resource-enactment/synthetic-test/1","walltime_seconds":3600}},"protocol":"auto-g16-v3-rtwin-bootstrap/2"}
```

The other six operation request/response schemas replay `/1` exactly except
their top-level protocol literal is `/2`. The `/2` current runtime-content set
has exactly four required names: `transport-deployment-manifest-v1.json`,
`auto-g16-rtwin-operation-table/2`,
`auto-g16-v3-rtwin-bootstrap-v2.py`, and
`pbs-resource-enactment-v1.json`. The manifest schema stays `/1` but its
`bootstrap_protocol` is exactly `/2`. TransportStore schema-v1 is unchanged:
its runtime row records the resolved-profile identity plus manifest, table-v2,
and source-v2 identities; the dialect descriptor is already transitively bound
by that resolved-profile identity and is reverified directly against the
snapshot runtime identity on every authority resolution. It is not duplicated
as a second mutable store authority.

The `/2` `SUBMIT_QSUB_ONCE` response also replays `/1` exactly except its
top-level protocol literal is `/2`: top-level keys are exactly `operation`,
`protocol`, `result`, and `status`; operation echoes `SUBMIT_QSUB_ONCE`, status
is `ok`, and result contains exactly one strict normalized PBS `job_id`. It
contains no resource, dialect, renderer, argv, executable, environment, or
other echo/evidence field. The exact canonical response is 123 bytes with
SHA-256 `c1a9556d75c9f0fc390ed89100a1241c1fc44abb6d1f2b568a476445672fa2d3`:

```json
{"operation":"SUBMIT_QSUB_ONCE","protocol":"auto-g16-v3-rtwin-bootstrap/2","result":{"job_id":"123.server"},"status":"ok"}
```

The exact Torque-capable Phase-B fixed successor source is
`auto-g16-v3-rtwin-bootstrap-v2.py`: 15597 UTF-8/ASCII bytes, exactly 204 LF,
zero CR/NUL, and SHA-256
`b0b1bcaf8ab8697a80676ac1015503a2fb64c21949678f20bf05f3bd849fb10e`.
It starts with `from __future__ import annotations\n`, ends with `main()\n`,
and contains the closed request validation, unchanged synthetic vector with
pre-qsub non-production rejection, and the exact Torque vector construction
above. Any source name, byte, line-ending, size, count, or digest drift rejects
during profile/snapshot resolution. The pre-Phase-B integrated source was
15195 bytes, 201 LF, with SHA-256
`3f3653a8b13d4cb5a5f5ba6e9caa02c3049caf144af13fd4491674c1fc7eb2f3`;
it remains immutable historical evidence and is not an accepted production-
Torque source.

<!-- Moved from docs/v3/boundary-spec.md:4825-4859 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## Scheduled job working-directory enactment

The resource renderer also derives one mechanical workdir argument from the
already-bound `remote_workspace`. Its semantic source is exclusively
`ExecutionSnapshot.workspace_binding.remote_attempt_dir`; it is not a resource
field and does not enter `ResourceEnactment`. For the exact Torque dialect the
complete argument tuple is:

```text
("-d", "<exact remote Attempt workspace>",
 "-l", "nodes=1:ppn=C,mem=Mmb,walltime=W",
 "-q", "batch", "B")
```

The qsub client continues to execute with descriptor-derived cwd equal to the
same workspace. Immediately before qsub, the bootstrap reopens the exact named
workspace no-follow, replays its frozen physical token, and compares the named
descriptor's device/inode with the retained descriptor. Any path, symlink,
replacement, token, or descriptor mismatch rejects before qsub.

The request schema is unchanged: `remote_workspace` remains in the existing
submitted binding and no argv/workdir value is accepted from the payload. The
private operation table declares `remote_workspace` as a submit renderer input
and its cwd policy covers both qsub client and scheduled shell. Protocol `/2`,
the seven operations, manifest schema v2, and public APIs are unchanged.

The exact successor operation table is 1623 bytes with SHA-256
`ce3efce070694831c32dbadd71fc2e7991f02cd985055193966666ea19dc9ffc`.
The fixed Python-3.6 bootstrap is 15926 bytes, 210 LF, zero CR/NUL, with
SHA-256 `a90edecf87916c149e865256d69e6f57820cb29336380bd45d2107c7c00c64f0`.
The corresponding source-controlled RTwin launcher-v5 is 11790 bytes, 200 LF,
with SHA-256
`184b806c07f05fdd1e51a669e9ff245f43c22b22b2efa17e5578f501d2e2d06d`.
Predecessor identities remain immutable historical evidence.
