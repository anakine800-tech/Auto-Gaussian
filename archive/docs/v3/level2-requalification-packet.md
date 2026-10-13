# Auto-G16 V31 offline Level-2 requalification packet

`scripts/prepare_v31_level2_packet.py` prepares one non-authoritative review
packet for one fresh xTB or CREST Attempt candidate. It creates no Core or
Approval store records. It cannot observe a Project, connect to a server,
install or launch a program, submit, cancel, retry, or accept science.

The resulting status is always `BLOCKED_ON_LIVE_PREREQUISITES`, including
when every supplied byte is internally consistent. Source/profile/program
facts are supplied evidence, not observations performed by this tool. The
packet has `live_authorized: false`, `execution_ready: false`, null approval
decisions, and a null real `ProgramExecutionSnapshot` with state
`DEFERRED_UNTIL_AUTHORIZED_CURRENT_ATTESTATION`. This is useful completed
offline preparation; it is not a failed scientific run or live readiness.

## Invocation and local output

Run from an inspected checkout with its supported core interpreter:

```text
./scripts/python core scripts/prepare_v31_level2_packet.py \
  --request /absolute/private/level2-request.json \
  --expected-main-sha <exact-40-character-main-SHA> \
  --output /absolute/private/new-level2-packet.json
```

The two SHA fields must agree exactly. The tool does not run Git or claim
that the supplied SHA is currently authoritative main. The integration owner
must independently bind main before using the packet, then recheck it at the
eventual live gate. The output records this limit as
`CALLER_BOUND_NOT_GIT_ATTESTED`.

Both paths must be absolute, with existing parents. Parent traversal and
terminal opens do not follow symlinks. Output uses exclusive creation,
mode 0600, and file/parent fsync; existing output is never overwritten.
Keep real packet bytes outside Git. A write failure can leave a partial
new output: preserve it and choose a new reviewed output path, without
automatic removal or replacement. Exit 0 means the blocked review packet
was written; exit 2 means rejected input or local I/O failure.

## Closed request format

The request is UTF-8 JSON, bounded to 256 MiB. Duplicate keys, nonfinite
numbers, unknown top-level fields, and malformed nested closed records
reject. All these top-level fields are required:

| Field | Required content |
| --- | --- |
| `schema` | Exact `auto-g16-v31-level2-review-request/1` |
| `main_sha` | Exact lowercase 40-character commit SHA |
| `request_id` | Explicit canonical UUID for this intended preparation |
| `project` | `project_id`, `remote_project_dir`; a distinct child of the profile's fixed root |
| `workflow` | `workflow_run_id`, `workflow_name`, `project_id`; same Project |
| `batch_purpose` | Explicit nonempty review purpose |
| `program_kind` | `xtb` or `crest` |
| `program_data` | Exact current source-owned adapter fields, with every scientific parameter explicit |
| `plan_intent` | Explicit plan meaning, including matching `program_kind`, `program_data`, and `input_sha256` |
| `displayed_scientific_meaning` | Nonempty expanded semantics for the human reviewer |
| `resources` | Positive integer `cores`, `memory_mb`, `walltime_seconds`, and exact `queue: "batch"` |
| `input` | `portable_name`, canonical `content_base64`, exact `sha256`, integer `size_bytes` |
| `server_profile` | Full encoded `ServerProfile`, or null if unavailable |
| `program_identities` | Exactly `xtb` and `crest`, each an identity object or null |

Input must be one syntactically valid XYZ frame with finite coordinates and
the exact declared hash/size. This is not chemical, stereochemical, charge,
or multiplicity acceptance. The tool never chooses method, solvent, spin,
resource values, or CREST sampling policies from the structure. Every such
choice and the expanded displayed meaning remain subject to human review.

`program_data` is validated through the existing private adapters in
`auto_g16/execution/program.py`. xTB uses the current v2 runtime-data
authority. CREST uses the current iMTD-GC v2 adapter and requires engine
version exactly `3.0.2`; historical ttconf replay is not a new candidate.
An xTB-to-CREST dependency is not materialized by this tool: after the
approved upstream result exists and is reviewed, prepare a new exact
downstream input packet. No dependent output is invented in advance.

Each program identity has exactly `absolute_path`, positive `size_bytes`,
lowercase SHA-256 `sha256`, and `version`; CREST must be `3.0.2`. A supplied
identity must match the resolved profile's program path and runtime-content
identity. A version string remains a supplied claim, not a version probe.

The encoded profile uses exactly the fields of `ServerProfile`. JSON
`jump_topology` is an array of three-element arrays. `config_files` is an
ordered array of objects with `logical_name` and `content_base64`.
`runtime_contents` maps logical names to canonical base64 of exact existing
content bytes. All other fields have their existing model meaning. The
resolver retains its secret-content rejection and xTB manifest validation.
Neither the profile's configured paths nor executable paths are opened.
Supplying exact executable content bytes may make the private request large;
the packet outputs identities rather than duplicating those content bytes.

Null profile or program identities produce an explicit partial packet with
missing-prerequisite blockers and no unsupported preview. Invalid supplied
facts reject rather than being silently omitted. Synthetic identities can
exercise the preparation code but can never produce a production readiness
claim, even when they are internally consistent.

## Output and next gates

Request content and UUID deterministically bind new candidate Batch, Task,
Attempt, CalculationPlan and ResourceSpec IDs. Repeating identical input
produces identical bytes and IDs; changed input or UUID produces different
candidate IDs. These are not proof of freshness or permission to create a
replacement Attempt. The owner must reconcile IDs and the target workspace
against current durable records before any persistence or effect.

Program spec, PBS bytes/hash and qsub argument previews reuse the source
renderers. An input name cannot collide with the scheduler or output names.
The exact qsub executable/argv is included only when the supplied successor
manifest and resource descriptor pass their existing closed validators and
frozen Torque identity checks. Otherwise only a clearly marked argument-tail
preview is present; executable authority remains deferred. No preview is
ever executed.

The packet includes zero currently authorized effects, a proposed bounded
one-Attempt budget, expected evidence inventory, required human decisions,
stop conditions, and a reconciliation procedure. Project observation and
any provisioning need their own gates. Actual snapshot preparation requires
the existing factory's fresh current Project attestation; this tool never
calls that factory or substitutes a synthetic privilege. Three explicit human
decisions and a fresh Live Owner Gate remain mandatory before any submission.

On `UNKNOWN`, retain the exact response bytes, receipts, Attempt/snapshot/job
lineage and request separately authorized reconciliation. No automatic retry,
new Attempt, qdel, deletion or cleanup follows. Scheduler terminal status and
raw evidence are not scientific acceptance.

Historical `682.master` stays `LEVEL2_TERMINAL_EVIDENCE_INCOMPLETE`, with
`retroactively_repaired: false`. The packet calls for fresh scientific Level-2
qualification; it cannot repair or relabel that historical result.

The packet SHA-256 covers canonical UTF-8 JSON with sorted keys, compact
separators and one terminal LF, excluding the `packet_sha256` field itself.
It detects byte drift, not human authorization or production truth.

## Bounded offline validation

```text
./scripts/python core scripts/run_tests.py tests.v31.tooling.test_prepare_v31_level2_packet tests.v3.execution.test_v31_lane_a.ProgramSpecTests
```

The new tests cover deterministic identity/lineage, malformed and spliced
inputs, partial production prerequisites, renderer consistency, no-follow
exclusive output, preserved historical failure, and tripwires on subprocess,
socket, snapshot-attestation and Approval factory calls. Fixtures are
synthetic. No complete-full or live test is needed to exercise this tool.
