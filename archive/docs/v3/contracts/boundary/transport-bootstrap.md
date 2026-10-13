# Auto-G16 v3 boundary: transport-bootstrap

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [Exact minimum Transport public inventory](transport-composition.md#exact-minimum-transport-public-inventory)
- [Snapshot-derived PBS resource enactment](transport-resources.md#snapshot-derived-pbs-resource-enactment)
- [Exact Torque 6.1.0 production dialect](transport-resources.md#exact-torque-610-production-dialect)
- [Historical bootstrap /1 source-controlled operation construction](transport-bootstrap-v1.md#historical-bootstrap-1-source-controlled-operation-construction)
- [Historical bootstrap /1 canonical deployment-manifest vector](transport-bootstrap-v1.md#historical-bootstrap-1-canonical-deployment-manifest-vector)
- [Historical bootstrap /1 fixed source and remote-shell grammars](transport-bootstrap-v1.md#historical-bootstrap-1-fixed-source-and-remote-shell-grammars)

<!-- Moved from docs/v3/boundary-spec.md:3719-4292 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-TRANSPORT-BOOTSTRAP-CHAIN-03 Physical and Bootstrap Authority Closeout

This integrated section freezes the TransportStore, physical-binding, threat
model, and trust-chain semantics retained by resource-enactment `/2`. Its
protocol/table/source names and exact canonical runtime vectors describe the
historical `/1` integration only. For the executable successor, the `/2`
runtime inventory and attestation handling under
`Snapshot-derived PBS resource enactment` are authoritative; no SQLite schema
or public store API changes.

**Contract status: FROZEN CANDIDATE; IMPLEMENTATION NOT AUTHORIZED BY THIS
DOCUMENT.** This additive closeout preserves the physical-authority decisions
and resolves the bootstrap/deployment trust-chain findings without changing
Core, Execution, receipt, Approval, Workflow,
Observe, Result, ScientificValidation, or Review APIs/schemas. When this exact
authority content is present on authoritative main after independent review,
the task is `CLOSED / FROZEN / INTEGRATED` and the successor offline Transport
implementation is gate-eligible. `V30-VAL-TRANSPORT-01` is already integrated;
Transport product paths use `affected / fail_closed=false` validation.
Commits `798d3559d7c5ee6211a0b29977310f8adb871a5f`,
`e49136e23c564cc9e0d9d97b905e43c45db73adc`, and
`44db04180af8222c6e4619accfab0049e89bd3e0` remain immutable failed evidence.
The last lacked exact per-operation request/response schemas and a realizable
single fetch response channel; this successor closes that remaining bootstrap
protocol defect class.

### Public surface and ownership

The exact Transport export inventory above expands from eight symbols to nine
by adding `TransportStore`; the not-yet-integrated Transport
`ExactRemoteJobBinding` expands only by its two store identity fields. No
already-integrated upstream public record changes. The store's exact public
lifecycle is:

```text
TransportStore.create_new(
    path: str | os.PathLike[str],
    *,
    approved_root: str | os.PathLike[str],
) -> TransportStore
TransportStore.open_existing(
    path: str | os.PathLike[str],
    *,
    approved_root: str | os.PathLike[str],
) -> TransportStore
TransportStore.close() -> None
```

There is no public generic `put`, SQL, token, transaction, migration, delete,
or authority-query method. Package-private adapter methods append and replay
the exact rows below. `RTWinExecutionAdapter` and `RTWinReadAdapter` each
require one `transport_store: TransportStore` keyword argument and must share
the same durable database for one Attempt. An already-closed store, wrong store
schema/identity, or store swap fails before any driver call.

`TransportStore` is owned entirely by `auto_g16.transport`. It is independent
of the Core SQLite store and Execution `ReceiptJournal`; it adds no table,
migration, or method to either owner. It persists physical operation evidence
only. A valid row cannot claim Core `WINNER`, confirm an effect, authorize a
read, create a receipt, resolve `UNKNOWN`, retry, cancel, delete, or grant
scientific authority.

### Exact threat model

This closeout detects accidental or unprivileged copy, alias, replacement,
path/root drift, stale reopen, and cross-store evidence splicing. It provides
store-instance binding and clone/replacement detection within that model; it
does **not** claim cryptographic uncloneability or protection from a malicious
same-UID process, root/administrator, kernel/filesystem compromise, or a
compromised deployment/bootstrap trust root. Those actors can copy database
bytes, forge ordinary filesystem metadata, replace trusted executables, or
interfere after an OS path check. Such compromise is outside this offline
product boundary and requires host/deployment/security authority, not a hidden
Transport capability scheme.

Within the model, create-new obtains a non-caller-selectable 32-byte nonce from
the operating-system CSPRNG exactly once, persists it before returning the
store, and never regenerates it on reopen. Store instance evidence also closes
the physical database file identity, approved lexical store path/root, and the
ordered physical identity chain from approved root through the database parent.
This is the strongest supported local clone/replacement evidence, not a promise
against an excluded actor that can control the same UID or kernel.

### Exact SQLite schema-v1

The database uses `PRAGMA application_id = 1093879636` (`A3GT`),
`user_version = 1`,
`foreign_keys = ON`, `trusted_schema = OFF`, and `synchronous = FULL`.
Its application objects are exactly these six tables plus package-owned
BEFORE-UPDATE and BEFORE-DELETE abort triggers for every table:

```text
transport_meta(
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_identity BLOB NOT NULL,
  transport_store_id TEXT NOT NULL UNIQUE,
  store_instance_id TEXT NOT NULL UNIQUE,
  creation_nonce BLOB NOT NULL CHECK(length(creation_nonce) = 32),
  approved_store_root TEXT NOT NULL,
  approved_store_path TEXT NOT NULL,
  store_file_identity BLOB NOT NULL,
  parent_identity_chain BLOB NOT NULL
)

transport_runtime_attestation(
  runtime_attestation_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  resolved_server_profile_id TEXT NOT NULL,
  effective_config_sha256 TEXT NOT NULL,
  deployment_manifest_name TEXT NOT NULL,
  deployment_manifest_sha256 TEXT NOT NULL,
  deployment_manifest_size_bytes INTEGER NOT NULL,
  deployment_id TEXT NOT NULL,
  bootstrap_protocol TEXT NOT NULL,
  operation_table_sha256 TEXT NOT NULL,
  operation_table_size_bytes INTEGER NOT NULL,
  bootstrap_source_name TEXT NOT NULL,
  bootstrap_source_sha256 TEXT NOT NULL,
  bootstrap_source_size_bytes INTEGER NOT NULL,
  payload BLOB NOT NULL
)

transport_workspace_authority(
  workspace_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  remote_workspace TEXT NOT NULL,
  workspace_physical_token BLOB NOT NULL,
  payload BLOB NOT NULL,
  UNIQUE(attempt_id, execution_snapshot_id, submission_intent_id,
         remote_workspace)
)

transport_artifact_authority(
  artifact_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  workspace_authority_id TEXT NOT NULL
    REFERENCES transport_workspace_authority(workspace_authority_id),
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  artifact_kind TEXT NOT NULL,
  logical_name TEXT NOT NULL,
  remote_relative_name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  artifact_physical_token BLOB NOT NULL,
  payload BLOB NOT NULL,
  UNIQUE(workspace_authority_id, artifact_kind, logical_name),
  UNIQUE(workspace_authority_id, remote_relative_name)
)

transport_job_authority(
  job_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  workspace_authority_id TEXT NOT NULL UNIQUE
    REFERENCES transport_workspace_authority(workspace_authority_id),
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  payload BLOB NOT NULL
)

transport_receipt_binding(
  receipt_binding_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  job_authority_id TEXT NOT NULL UNIQUE
    REFERENCES transport_job_authority(job_authority_id),
  workspace_authority_id TEXT NOT NULL
    REFERENCES transport_workspace_authority(workspace_authority_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  remote_effect_receipt_id TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL,
  payload BLOB NOT NULL
)
```

The exact append-only trigger names are
`transport_meta_no_update`, `transport_meta_no_delete`,
`transport_runtime_attestation_no_update`,
`transport_runtime_attestation_no_delete`,
`transport_workspace_authority_no_update`,
`transport_workspace_authority_no_delete`,
`transport_artifact_authority_no_update`,
`transport_artifact_authority_no_delete`,
`transport_job_authority_no_update`, `transport_job_authority_no_delete`,
`transport_receipt_binding_no_update`, and
`transport_receipt_binding_no_delete`; each executes `RAISE(ABORT, ...)` before
its named operation. `transport_meta` has exactly one `singleton = 1` row.
`schema_identity` binds the ordered SQL object inventory and schema-v1 DDL;
the remaining exact fields bind the logical store, one physical instance, its
one-time nonce, approved lexical root/path, file identity, and ordered parent
identity chain. Every evidence row repeats exact `transport_store_id` and
`store_instance_id`; a cross-store row rejects even if every other field and
payload byte is copied. Every foreign identity is
replayed in application code and by foreign keys where applicable. On every
open, the store attests application/user versions, the exact meta row, every
table/column/index/foreign-key/trigger definition, and rejects unexpected
application objects, missing append-only triggers, malformed rows, identity
drift, natural-key conflicts, or foreign-binding mismatch. Every adapter read
or append repeats schema/meta attestation inside one `BEGIN IMMEDIATE`
transaction before using rows; it never relies only on the constructor-time
check or an unlocked check-then-use interval.

Each runtime row requires manifest name exactly
`transport-deployment-manifest-v1.json`, bootstrap protocol exactly
`auto-g16-v3-rtwin-bootstrap/1`, and manifest digest/size/deployment ID exactly
from canonical bytes already closed against the current snapshot. Its operation
table and bootstrap-source identities equal the two other fixed runtime-content
entries. No row supplies or overrides manifest bytes; it only records the
already-validated deployment/profile identity for cross-profile replay checks.

The caller supplies both one path and its independently deployment-approved
local store root; the persisted root cannot approve itself on reopen. Transport
normalizes both to absolute lexical paths without `resolve()` or `realpath()`,
requires the path to be a strict descendant of that root, opens the approved
root descriptor, and walks the relative parent chain descriptor-relative and
no-follow. Every component must be an expected directory; symlink/reparse,
root escape, replacement, or chain mismatch rejects.
The ordered parent identities are captured from held descriptors. An existing
terminal symlink or non-regular file rejects. Create-new uses no-follow
`O_CREAT | O_EXCL`; reopen records the terminal file identity before SQLite
open and reattests the same lexical file and parent chain immediately after
open. No pathname fallback, overwrite, replacement, or migration is allowed.
The strongest practical pre/post SQLite transaction check reattests approved
root, parent chain, path, regular-file type, and file identity before and after
every transaction. Exact reopen remains durable and idempotent within the
threat model. This does not claim an atomic path/SQLite capability or eliminate
TOCTOU against an excluded malicious same-UID/root/kernel actor.

### Store identity and replay

Store identities reuse the frozen Transport namespace root
`6e54140f-f4e7-5482-a6c1-8f5729e3c112`, canonical tagged encoding, and
`uuid5(domain_namespace, canonical_bytes.decode("ascii"))`. New domain
namespaces are exactly:

```text
transport-store     -> 08b51475-e12f-5c8a-9c29-ac1a50c4778d
store-instance      -> 10b04ccd-414d-502e-a23b-8347087797fd
runtime-attestation -> 4fd2e62a-471b-5cdf-a41c-c73cd15df6be
workspace-physical  -> cf5d20c0-dcf7-5017-b550-a4b86d2e2315
artifact-physical   -> 1bb613c9-3d29-584e-a061-ba3bf03589b5
job-physical        -> d82d6457-637e-5262-8741-d721d2b5057f
receipt-binding     -> 26685dd2-091e-5476-9556-1b6416d6a200
```

`creation_nonce` is exactly 32 raw bytes. The canonical POSIX physical file
identity is `['posix-file', st_dev, st_ino, 'regular']`. Each canonical parent
entry is `[absolute_lexical_component_path, st_dev, st_ino, 'directory']`;
`parent_identity_chain` is the ordered non-empty array beginning with the
approved root and ending with the database's direct parent. Equivalent Windows
implementation uses `['windows-file', volume_serial_number,
file_id_128_hex, 'regular']` and parent entries with `directory`; reparse points
reject. One store uses exactly one platform form and cannot change form on
reopen.

The complete schema-v1 identity-name arrays are exactly:

```text
["auto-g16-transport/store", 1,
 approved_store_root, approved_store_path]

["auto-g16-transport/store-instance", 1,
 transport_store_id, creation_nonce, approved_store_root,
 approved_store_path, store_file_identity, parent_identity_chain]

["auto-g16-transport/runtime-attestation", 1,
 transport_store_id, store_instance_id,
 execution_snapshot_id, resolved_server_profile_id,
 effective_config_sha256, deployment_manifest_name,
 deployment_manifest_sha256, deployment_manifest_size_bytes,
 deployment_id, bootstrap_protocol, operation_table_sha256,
 operation_table_size_bytes, bootstrap_source_name, bootstrap_source_sha256,
 bootstrap_source_size_bytes]

["auto-g16-transport/workspace-physical", 1,
 transport_store_id, store_instance_id,
 runtime_attestation_id, attempt_id, execution_snapshot_id,
 submission_intent_id, remote_workspace, workspace_physical_token]

["auto-g16-transport/artifact-physical", 1,
 transport_store_id, store_instance_id,
 workspace_authority_id, runtime_attestation_id, attempt_id,
 execution_snapshot_id, submission_intent_id, artifact_kind, logical_name,
 remote_relative_name, sha256, size_bytes, artifact_physical_token]

["auto-g16-transport/job-physical", 1,
 transport_store_id, store_instance_id,
 workspace_authority_id, runtime_attestation_id, attempt_id,
 execution_snapshot_id, submission_intent_id, job_id]

["auto-g16-transport/receipt-binding", 1,
 transport_store_id, store_instance_id,
 job_authority_id, workspace_authority_id, attempt_id,
 execution_snapshot_id, submission_intent_id,
 remote_effect_receipt_id, job_id]
```

`transport_store_id` is the deterministic logical identity of one approved
root/path pair. `store_instance_id` is the identity of one creation at that
pair and binds the one-time nonce plus then-current physical file/parent chain.
A byte-for-byte database clone at another path, another file identity, or
another parent chain cannot satisfy both IDs within the threat model. Reopen at
the same approved path and physical identity preserves both IDs. Neither ID is
a secret or an unforgeable capability.

The normative store fixture uses approved root
`/var/lib/auto-g16/transport`, approved path
`/var/lib/auto-g16/transport/store.sqlite3`, nonce bytes
`000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f`,
file identity `['posix-file', 42, 9001, 'regular']`, and parent chain
`[['/var/lib/auto-g16/transport', 42, 8001, 'directory']]`. That nonce is a
deterministic test fixture only; production creation must use the OS CSPRNG.
The exact canonical bytes and UUIDs are:

```text
transport-store bytes:
a4:s24:auto-g16-transport/storei1;s27:/var/lib/auto-g16/transports41:/var/lib/auto-g16/transport/store.sqlite3
transport_store_id:
108c8d43-2ea9-5658-9607-ade4cbbeac85

store-instance bytes:
a8:s33:auto-g16-transport/store-instancei1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85y32:000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1fs27:/var/lib/auto-g16/transports41:/var/lib/auto-g16/transport/store.sqlite3a4:s10:posix-filei42;i9001;s7:regulara1:a4:s27:/var/lib/auto-g16/transporti42;i8001;s9:directory
store_instance_id:
28c10d1a-9f8f-5ce6-84d1-555175c0fcde
```

The following superseded identity-codec fixture is retained only as readable
negative evidence from failed candidate `e49136e23c564cc9e0d9d97b905e43c45db73adc`.
It uses `snapshot-1`, `profile-1`,
`attempt-1`, `intent-1`, remote workspace `/srv/p/attempt-1`, job
`123.server`, receipt `receipt-1`, workspace token `workspace-token-v1`, and
prepared-input token `artifact-token-v1`. Its fixed nested raw-byte executable
payload preserves the earlier codec vector with digest
`4e31987b253d5d9edb353074f91ad39c0544f5f18ec8571da45af457faa85451`.
It is not current authority or deployment-manifest evidence; the semantic
manifest validator must reject that abbreviated four-field payload and its
dependent IDs. The superseded bytes were:

```text
superseded runtime-attestation bytes:
a13:s38:auto-g16-transport/runtime-attestationi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes10:snapshot-1s9:profile-1s64:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaas64:3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1i1040;s64:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbi2048;y889:61333a7334303a6175746f2d6731362d7472616e73706f72742f65786563757461626c652d6964656e74697469657369313b61383a61343a73373a6d61632d7373687331303a2f782f6d61632d7373687336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369313b61343a73373a6d61632d7363707331303a2f782f6d61632d7363707336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369323b61343a73393a727477696e2d7373687331323a2f782f727477696e2d7373687336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369333b61343a73393a727477696e2d7363707331323a2f782f727477696e2d7363707336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369343b61343a7331323a727477696e2d6272696467657331353a2f782f727477696e2d6272696467657336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369353b61343a7331333a7365727665722d707974686f6e7331363a2f782f7365727665722d707974686f6e7336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369363b61343a7331313a7365727665722d717375627331343a2f782f7365727665722d717375627336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369373b61343a7331323a7365727665722d71737461747331353a2f782f7365727665722d71737461747336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369383bs64:4e31987b253d5d9edb353074f91ad39c0544f5f18ec8571da45af457faa85451
superseded runtime_attestation_id:
d497b2fa-c567-5c44-bb49-1ec01586d4cd

superseded workspace-physical bytes:
a10:s37:auto-g16-transport/workspace-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s16:/srv/p/attempt-1y18:776f726b73706163652d746f6b656e2d7631
superseded workspace_authority_id:
8bc410b7-b0ed-5050-bc53-b75126610f45

superseded artifact-physical bytes:
a15:s36:auto-g16-transport/artifact-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:8bc410b7-b0ed-5050-bc53-b75126610f45s36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s14:prepared-inputs7:job.gjfs7:job.gjfs64:ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddi123;y17:61727469666163742d746f6b656e2d7631
superseded artifact_authority_id:
c140b8e0-93e2-566d-b1c6-d0e6b0d86522

superseded job-physical bytes:
a10:s31:auto-g16-transport/job-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:8bc410b7-b0ed-5050-bc53-b75126610f45s36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s10:123.server
superseded job_authority_id:
12ae30ec-eaa5-516f-9967-4a4987b86f9d

superseded receipt-binding bytes:
a11:s34:auto-g16-transport/receipt-bindingi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:12ae30ec-eaa5-516f-9967-4a4987b86f9ds36:8bc410b7-b0ed-5050-bc53-b75126610f45s9:attempt-1s10:snapshot-1s8:intent-1s9:receipt-1s10:123.server
superseded receipt_binding_id:
3e51a223-b74b-5f9a-946d-3c4e0b419a39
```

The active complete-manifest fixture uses the normative manifest identity
above, operation-table digest/size above, bootstrap-source name
`auto-g16-v3-rtwin-bootstrap-v1.py`, the exact source digest
`056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`
and size `13904`, effective-config digest `a` repeated 64 times, and the same
remaining literal inputs. Its exact current canonical vectors are:

```text
runtime-attestation bytes:
a17:s38:auto-g16-transport/runtime-attestationi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes10:snapshot-1s9:profile-1s64:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaas37:transport-deployment-manifest-v1.jsons64:70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983ai2753;s29:synthetic-rtwin-deployment-v1s29:auto-g16-v3-rtwin-bootstrap/1s64:6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6i1490;s33:auto-g16-v3-rtwin-bootstrap-v1.pys64:056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952i13904;
runtime_attestation_id:
55823409-18d5-5ec8-8cd1-95fc2070fcfa

workspace-physical bytes:
a10:s37:auto-g16-transport/workspace-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s16:/srv/p/attempt-1y18:776f726b73706163652d746f6b656e2d7631
workspace_authority_id:
ceff0991-4089-5c97-90b5-199c00467e67

artifact-physical bytes:
a15:s36:auto-g16-transport/artifact-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:ceff0991-4089-5c97-90b5-199c00467e67s36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s14:prepared-inputs7:job.gjfs7:job.gjfs64:ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddi123;y17:61727469666163742d746f6b656e2d7631
artifact_authority_id:
5ed7b28e-72ab-55b7-8c66-37f2d5ecab11

job-physical bytes:
a10:s31:auto-g16-transport/job-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:ceff0991-4089-5c97-90b5-199c00467e67s36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s10:123.server
job_authority_id:
51eef369-a569-53e2-8c44-2d22e20057f7

receipt-binding bytes:
a11:s34:auto-g16-transport/receipt-bindingi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:51eef369-a569-53e2-8c44-2d22e20057f7s36:ceff0991-4089-5c97-90b5-199c00467e67s9:attempt-1s10:snapshot-1s8:intent-1s9:receipt-1s10:123.server
receipt_binding_id:
e824ab64-5fcf-5014-be1a-b53ad70f8cce
```

The `payload` column is the exact canonical encoding of the corresponding
array. Physical tokens are immutable raw bytes, length `1..4096`; Transport
does not parse, synthesize, shorten, or treat them as secrets. The trusted
remote agent alone creates and reattests them. Same identity plus byte-identical
payload is an idempotent replay. Same identity/different payload, a different
identity for one natural binding, a duplicate job for one workspace, or a
receipt/job mismatch is a `TransportBoundaryError` and leaves the database
unchanged. Append uses one immediate transaction; zero-row or multi-row
trigger interference, suppressed insert, mutation, or post-insert mismatch
fails closed. Failure after a possibly effectful remote operation remains
possibly effectful/`UNKNOWN`; it never causes automatic replay of that
operation.

The runtime row repeats the exact manifest name, byte identity, deployment ID,
bootstrap protocol, operation-table identity, and fixed bootstrap-source
identity from the current resolved profile/snapshot. It stores no second
manifest projection and no independently caller-supplied executable inventory.
Every workspace/artifact/job/receipt row links that runtime row, preventing
cross-profile or cross-deployment replay while keeping deployment trust and
physical-object evidence separate.

`transport_artifact_authority` stores only the two effect-side staged artifacts.
Its `artifact_kind` is exactly `prepared-input` or `pbs-template`; its logical
and remote-relative names, digest, and size must equal the corresponding exact
`ExecutionSnapshot` prepared-artifact binding. Generated Gaussian output is
not inserted into this table because output may grow across legal captures.

The effect adapter appends runtime attestation before the operation, workspace
authority immediately after fresh allocation, artifact authority immediately
after each exact staged write, and job authority after strict qsub extraction
or confirmed same-Attempt reconciliation. Once the public ReceiptJournal has
durably appended the matching confirmed receipt,
`ExactRemoteJobBinding.from_persisted_receipt(...)` appends/replays the exact
receipt-binding row before returning. This split preserves the unchanged
ExecutionPort and receipt APIs while making process restart safe.

### Replacement-safe remote physical authority

The installed remote agent begins from the approved root descriptor. Fresh
allocation walks and creates every Attempt-workspace component descriptor-
relative and no-follow, then returns the opaque workspace token only after the
new final directory is reattested. Existing targets, symlink/reparse points,
replacement, escape, or inability to obtain a stable token fail closed.

Every later stage, qsub, qstat, reconciliation, and fetch request carries the
exact persisted workspace token in the package-controlled physical-binding
envelope `auto-g16-rtwin-physical-binding/1`. The agent reopens from the root,
walks no-follow, compares the complete physical token, and performs the
operation relative to the still-held final descriptor. There is no
`resolve/check -> pathname mutation` fallback. Process restart is irrelevant:
the token is loaded from `TransportStore`, not an in-memory allocation set.

After a stage write, the agent returns an artifact token only after fresh
no-follow create, exact-byte digest/size verification, fsync as supported, and
descriptor reattestation. Qsub requires the exact two persisted staged
artifacts and reattests their tokens from the held workspace descriptor before
invocation. Fetch requires the persisted workspace token; for generated output
the agent creates one operation-local read token from bounded before/read/after
descriptor evidence and returns it with the exact bytes for adapter validation.
That evolving output token is not inserted into the staged-artifact table.
Cross-workspace, cross-Attempt, cross-snapshot, stale, replaced, or unpersisted
workspace/staged tokens reject before effect/read.

The physical-binding envelope is typed fixed data, not argv, a capability, or
an authority shortcut. The exact seven-operation table v1 tokens, argv
templates, limits, and digest are frozen above. A token never authorizes a new Attempt,
retry, qdel, delete, cleanup, profile change, or scientific conclusion.

### Bootstrap trust and fixed command construction

The exact manifest-bound `server_python` root is preinstalled and trusted by
deployment before it starts. It neither proves the manifest nor establishes its
own pre-start integrity. The configured RTwin and server remote shells likewise
start as explicit deployment roots. Their exact role, nine-root inventory, and
grammar-specific launchers are frozen in “Canonical deployment manifest” and
“Fixed bootstrap and remote-shell grammars” above; no universal pre-bootstrap
file verifier is claimed.

After start, the exact fixed bootstrap source accepts the seven operation enums,
physical-binding envelope, and bounded framed data only. No caller source,
module, bytecode, callback, command, shell fragment, executable, or operation is
uploaded or selected. The server process may detect drift in its own manifest
entry and attest exact qsub/qstat before absolute-path structured-argv launch;
RTwin executable checks remain owned by the deployment-trusted declared RTwin
shell. Missing/drifted evidence rejects with zero next operation. This grants
neither credential nor host-key authority; secrets remain out-of-band.

Controller Mac executables and post-bootstrap server executables use strict
prelaunch and practical postlaunch reattestation. Prelaunch drift causes zero
process call. Postlaunch drift makes evidence unusable and, if an effect may
have crossed, preserves `UNKNOWN` with no retry. This is replacement detection
inside the stated model, not a TOCTOU guarantee against excluded actors.
Descriptor execution and a native wrapper are neither required nor authorized.

The controller launches Mac OpenSSH by structured argv with local
`shell=False`; that does not remove either remote shell. Whenever Windows
`CreateProcess` serialization is required inside the frozen PowerShell
launcher, its parser contract is the Microsoft CRT/`CommandLineToArgvW`
backslash-and-double-quote grammar. The exact encoder leaves a nonempty
argument containing no space, tab, or `"` unchanged; otherwise it surrounds the
argument with `"`, doubles every run of backslashes immediately before a
literal `"`, prefixes that quote with one additional backslash, doubles
trailing backslashes before the closing `"`, and encodes an empty argument as
`""`. NUL is rejected. Tests round-trip every fixed nested SSH token. The
manifest-selected PowerShell/cmd and server POSIX shell grammars are the only
remote-shell interpretation and are never auto-detected or bypassed.

If the RTwin-to-server POSIX hop unavoidably accepts one command string,
Transport constructs it solely from the exact launcher tuple with the two
class-specific encoders frozen above. For every variable launcher token:

```text
quote_variable(token) = "'" + token.replace("'", "'\"'\"'") + "'"
```

Variable tokens containing NUL, CR, or LF reject and empty tokens encode as
`''`. Only the exact digest/size-closed protocol source uses
`quote_bootstrap_source`, which rejects NUL/CR but preserves LF and literal
single quotes as one word. The caller can supply no command token, source, or
shell fragment. Where an argv/subsystem form exists it is preferred and no
command string is built. All stdin/stdout/stderr/control channels are
separately bounded, require process completion and EOF, and reject overflow,
truncation, extra bytes, timeout, or unstable completion. No retry follows any
uncertain result.

### Frozen adversarial implementation matrix

Implementation must prove: create/reopen store; terminal-symlink and
replacement rejection; exact schema/object/trigger attestation; durable replay;
same-ID conflict; natural-binding conflict; trigger suppression/mutation;
workspace allocation replacement; component symlink/escape; process restart
between allocate/stage/qsub/read; stale or forged workspace token; both staged
artifact tokens; artifact replacement before qsub; job/receipt exact binding;
cross-store and cross-Attempt/snapshot/intent/workspace/job splicing; dynamic
caller source/module/command spies zero; every canonical manifest negative;
profile/snapshot/runtime-content mismatch; fixed bootstrap source/operation
table/frame drift; PowerShell file/hash/launcher drift; cmd incompatibility with
zero fallback; server shell/Python/qsub/qstat drift; digest-to-exec replacement;
PowerShell/CRT/cmd/POSIX quote vectors including empty, spaces, apostrophe,
metacharacters, and NUL/CR/LF rejection; bounded-channel overflow/EOF/timeout;
qsub at most
once; post-WINNER ambiguity to `UNKNOWN`; restart without automatic retry;
exact qstat/fetch after reopen; generated-output read-token stability; and zero
qdel/delete/cleanup/live calls.

The five already-reviewed product blobs outside the eventual narrow repair
delta remain byte-identical unless an independently reviewed implementation
finding proves a change uniquely required by this contract. OpenSSH, process
and Gaussian-phase acquisition, deployment, credentials, qdel, deletion,
cleanup, automatic retry, and every live operation remain deferred.
