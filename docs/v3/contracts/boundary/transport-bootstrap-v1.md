# Auto-G16 v3 boundary: transport-bootstrap-v1

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [Snapshot-derived PBS resource enactment](transport-resources.md#snapshot-derived-pbs-resource-enactment)
- [Exact Torque 6.1.0 production dialect](transport-resources.md#exact-torque-610-production-dialect)
- [Canonical transport evidence identity](transport-composition.md#canonical-transport-evidence-identity)
- [Replacement-safe remote physical authority](transport-bootstrap.md#replacement-safe-remote-physical-authority)

<!-- Moved from docs/v3/boundary-spec.md:3187-3628 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### Historical bootstrap /1 source-controlled operation construction

This subsection and its `/1` table, basename-only qsub, three-content runtime
inventory, bootstrap-source vector, and wire vectors are immutable historical
evidence for the integrated predecessor. Once the resource-enactment successor
is present, the `/2` rules above are current and override every `/1` statement
for executable Transport resolution; implementations must not satisfy both or
reinterpret `/1`.

The private operation table version is exactly
`auto-g16-rtwin-operation-table/1`. Its immutable entries are:

| operation | token | argv template | timeout seconds | stdin cap | stdout cap | stderr cap |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `ALLOCATE_WORKSPACE` | `allocate-workspace` | `()` | 30 | 65536 | 65536 | 65536 |
| `STAGE_EXACT_FILE` | `stage-exact-file` | `("{logical_name}", "{sha256}", "{size_bytes}")` | 900 | 179306496 | 65536 | 65536 |
| `SUBMIT_QSUB_ONCE` | `submit-qsub-once` | `("{pbs_basename}",)` | 30 | 65536 | 65536 | 65536 |
| `QUERY_SCHEDULER` | `query-scheduler` | `("-f", "{job_id}")` | 30 | 65536 | 524288 | 65536 |
| `STAT_EXACT_FILE` | `stat-exact-file` | `("{remote_relative_name}",)` | 30 | 65536 | 65536 | 65536 |
| `FETCH_EXACT_FILE` | `fetch-exact-file` | `("{remote_relative_name}",)` | 900 | 65536 | 179306496 | 65536 |
| `RECONCILE_SUBMISSION` | `reconcile-submission` | `()` | 30 | 65536 | 262144 | 65536 |

Every operation has `shell=False` at the final server operation/executable
seam, no retry, exact cwd equal to the remote Attempt workspace, and environment
exactly `LANG=C`, `LC_ALL=C`,
`PYTHONNOUSERSITE=1`, and `PYTHONUTF8=1`. The allocate operation is one fixed
driver primitive that creates the fresh remote Attempt directory no-follow and
treats the target workspace as its logical cwd; its argv is empty and it
accepts no parent/root or command string. Stage runs exactly twice in prepared
input then PBS-template order; each argv is
`(<logical_name>, <lowercase_sha256>, <base10_size_bytes>)` and exact bytes
travel in the framed data packet. Qsub argv is exactly
`(<one prepared PBS script basename>,)`; qstat argv is the exact tuple frozen
above; stat/fetch argv is exactly `(<one requested remote_relative_name>,)` for
each request in authoritative order. Reconciliation has no argv and consumes
only the exact binding data packet. Operation tokens are enum data, not
executable names or shell text. The `stdin_cap` and `stdout_cap` columns bound
the complete outer AGV3 request and response frames respectively. The inner
qstat raw stdout/stderr limits remain 262144/65536 bytes; their base64 fields
fit the 524288-byte outer response cap. A fetch returns its exact raw bytes only
as canonical base64 inside the one bounded stdout response frame described
below, never through an unspecified side channel or a local path. Every
operation requires process completion and EOF within all caps; fetch additionally
enforces the raw artifact and total-capture caps before encoding. Any timeout,
overflow, missing EOF, malformed completion, or possibly-effectful ambiguity
fails closed under the existing Execution uncertainty rules. No operation
token or argv fragment is caller supplied.

Allocate, stage, and qsub substitute only values from the current
identity-closed `ExecutionSnapshot`: exact remote Attempt workspace, the two
exact prepared artifact bindings/bytes, and the PBS basename. Qstat and fetch
substitute only fields from `ExactRemoteJobBinding` plus the validated ordered
`ExactArtifactRequest` tuple. The package-private driver accepts those typed
records and byte channels, never a free path, command string, environment, or
prebuilt argv.
This table field does not deny the two explicitly modeled SSH remote shells;
it forbids the fixed bootstrap from invoking another shell for an operation.

Under the canonical grammar above, the complete table object contains keys
`version`, `cwd_policy`, `shell`, `env`, `limits`, and `operations`; limits are
exactly request count 4, per-artifact bytes 134217728, and total-capture bytes
268435456; operations are the seven table rows in displayed order. Canonical
table bytes use the manifest JSON rules below, including one trailing LF. Their
byte size is `1490` and SHA-256 is
`6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6`.
The exact object shape used for that digest is:

```text
{
  "version": "auto-g16-rtwin-operation-table/1",
  "cwd_policy": "exact-remote-attempt-workspace",
  "shell": false,
  "env": {"LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1",
          "PYTHONUTF8": "1"},
  "limits": {"max_artifact_requests": 4,
             "max_artifact_bytes": 134217728,
             "max_capture_bytes": 268435456},
  "operations": [
    {"name": "ALLOCATE_WORKSPACE", "token": "allocate-workspace", "argv_template": [],
     "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "STAGE_EXACT_FILE", "token": "stage-exact-file",
     "argv_template": ["{logical_name}", "{sha256}", "{size_bytes}"],
     "timeout_seconds": 900, "stdin_cap": 179306496,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "SUBMIT_QSUB_ONCE", "token": "submit-qsub-once",
     "argv_template": ["{pbs_basename}"], "timeout_seconds": 30,
     "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "QUERY_SCHEDULER", "token": "query-scheduler",
     "argv_template": ["-f", "{job_id}"], "timeout_seconds": 30,
     "stdin_cap": 65536, "stdout_cap": 524288, "stderr_cap": 65536},
    {"name": "STAT_EXACT_FILE", "token": "stat-exact-file",
     "argv_template": ["{remote_relative_name}"],
     "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "FETCH_EXACT_FILE", "token": "fetch-exact-file",
     "argv_template": ["{remote_relative_name}"],
     "timeout_seconds": 900, "stdin_cap": 65536,
     "stdout_cap": 179306496, "stderr_cap": 65536},
    {"name": "RECONCILE_SUBMISSION", "token": "reconcile-submission",
     "argv_template": [], "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 262144, "stderr_cap": 65536}
  ]
}
```

The adapter accepts only an identity-closed current `ExecutionSnapshot` whose
resolved profile selects `legacy_rtwin_pbs`. The fixed runtime-content names
are exactly `transport-deployment-manifest-v1.json`,
`auto-g16-rtwin-operation-table/1`, and
`auto-g16-v3-rtwin-bootstrap-v1.py`; the latter is the one
fixed bootstrap-source/bridge content owned by protocol
`auto-g16-v3-rtwin-bootstrap/1`. Exact byte identities for all three must appear
in the snapshot's existing `runtime_identities`. Executable and remote-shell
paths come only from the manifest; Transport does not choose between those
values and duplicate `platform_paths` values. Existing `rtwin_root` and
`known_hosts` profile/config semantics remain bound by the resolved profile but
are not an alternate manifest.

The adapter calls public `assert_execution_snapshot_identity(...)`, obtains the
exact manifest bytes only from the retained/current public `ServerProfile`,
calls public `resolve_server_profile(...)`, and requires complete equality with
the snapshot's resolved profile plus exact manifest `bytes_identity` equality
with `runtime_identities["transport-deployment-manifest-v1.json"]`. Missing,
renamed, duplicated-by-alias, or changed bytes reject before parsing or any
driver call. It relies on `effective_config_sha256` for the already-closed SSH
config/known-host content and neither opens configuration files nor reads
private Execution internals.

These existing resolved profile mappings carry configuration and exact runtime
content identity only, never argv fragments, mutable environment,
credential material, private keys, passwords, tokens, or secret contents.
Host aliases and credential lookup remain driver-private and must match the
attested resolved profile target/config identity; they are not evidence
fields. If any table/runtime binding drifts, the adapter rejects before a port
call. No Core or Execution schema/API change is implied.

### Historical bootstrap /1 canonical deployment-manifest vector

The only manifest authority is the immutable bytes at
`ServerProfile.runtime_contents["transport-deployment-manifest-v1.json"]`.
Transport first resolves the current profile and closes it exactly against the
snapshot as above; it then requires the manifest byte identity
`{"sha256": lowercase_sha256, "size_bytes": positive_integer}` to equal that
exact fixed `runtime_identities` entry. No manifest parameter, alias, fallback,
ambient file, global singleton, latest/current lookup, or stored TransportStore
row may replace those bytes.

Manifest bytes are UTF-8 without BOM and are exactly one JSON object encoded by:

```text
json.dumps(
    object,
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8") + b"\n"
```

Parsing rejects duplicate keys, nonfinite numbers, invalid UTF-8, missing or
extra LF, and any byte sequence unequal to canonical replay. The top-level keys
are exactly `bootstrap_protocol`, `deployment_id`, `schema`, and
`trust_roots`. Constants are exactly
`auto-g16-v3-transport-deployment-manifest/1` and
`auto-g16-v3-rtwin-bootstrap/1`; `deployment_id` is a non-empty canonical
deployment-owned string, never ambiently discovered or generated per Attempt.
It and every other manifest string reject NUL, CR, and LF.

`trust_roots` has exactly `mac_ssh`, `mac_scp`, `rtwin_ssh`,
`rtwin_scp`, `rtwin_remote_shell`, `server_remote_shell`,
`server_python`, `server_qsub`, and `server_qstat`. Every value has exactly
`attestation_mode`, `deployment_identity`, `expected_sha256`,
`expected_size_bytes`, `path`, `platform`, and `shell_grammar`.
`deployment_identity` is non-empty; paths are absolute and platform-native;
platform is exactly `macos`, `windows`, or `posix`; a present digest is
lowercase 64-hex; and a present size is a positive non-boolean integer.

The exact per-name matrix is:

| root | platform | attestation mode | digest/size | shell grammar |
| --- | --- | --- | --- | --- |
| `mac_ssh` | `macos` | `controller-file-v1` | required | null |
| `mac_scp` | `macos` | `controller-file-v1` | required | null |
| `rtwin_ssh` | `windows` | `rtwin-shell-file-v1` | required | null |
| `rtwin_scp` | `windows` | `rtwin-shell-file-v1` | required | null |
| `rtwin_remote_shell` | `windows` | `deployment-root-v1` | null | exactly `powershell-v1` or `cmd-v1` |
| `server_remote_shell` | `posix` | `deployment-root-v1` | null | `posix-sh-v1` |
| `server_python` | `posix` | `server-self-check-v1` | required | null |
| `server_qsub` | `posix` | `server-python-file-v1` | required | null |
| `server_qstat` | `posix` | `server-python-file-v1` | required | null |

No tenth root, missing root, extra field, alternative mode, null outside the
two shell rows, or grammar inference is valid. Shell rows are deployment trust
roots and do not authenticate themselves before interpreting the first remote
command. `server_python` likewise starts from deployment trust; its
`server-self-check-v1` is post-start drift detection, not trust creation.

The complete normative synthetic manifest is the following single line plus
one LF:

```json
{"bootstrap_protocol":"auto-g16-v3-rtwin-bootstrap/1","deployment_id":"synthetic-rtwin-deployment-v1","schema":"auto-g16-v3-transport-deployment-manifest/1","trust_roots":{"mac_scp":{"attestation_mode":"controller-file-v1","deployment_identity":"synthetic-macos-openssh-9.8p1","expected_sha256":"2222222222222222222222222222222222222222222222222222222222222222","expected_size_bytes":1049600,"path":"/usr/bin/scp","platform":"macos","shell_grammar":null},"mac_ssh":{"attestation_mode":"controller-file-v1","deployment_identity":"synthetic-macos-openssh-9.8p1","expected_sha256":"1111111111111111111111111111111111111111111111111111111111111111","expected_size_bytes":1048576,"path":"/usr/bin/ssh","platform":"macos","shell_grammar":null},"rtwin_remote_shell":{"attestation_mode":"deployment-root-v1","deployment_identity":"synthetic-windows-powershell-5.1","expected_sha256":null,"expected_size_bytes":null,"path":"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe","platform":"windows","shell_grammar":"powershell-v1"},"rtwin_scp":{"attestation_mode":"rtwin-shell-file-v1","deployment_identity":"synthetic-windows-openssh-9.5p1","expected_sha256":"4444444444444444444444444444444444444444444444444444444444444444","expected_size_bytes":1110000,"path":"C:\\Windows\\System32\\OpenSSH\\scp.exe","platform":"windows","shell_grammar":null},"rtwin_ssh":{"attestation_mode":"rtwin-shell-file-v1","deployment_identity":"synthetic-windows-openssh-9.5p1","expected_sha256":"3333333333333333333333333333333333333333333333333333333333333333","expected_size_bytes":1100000,"path":"C:\\Windows\\System32\\OpenSSH\\ssh.exe","platform":"windows","shell_grammar":null},"server_python":{"attestation_mode":"server-self-check-v1","deployment_identity":"synthetic-server-python-3.13","expected_sha256":"5555555555555555555555555555555555555555555555555555555555555555","expected_size_bytes":1200000,"path":"/usr/bin/python3","platform":"posix","shell_grammar":null},"server_qstat":{"attestation_mode":"server-python-file-v1","deployment_identity":"synthetic-pbs-2024.1","expected_sha256":"7777777777777777777777777777777777777777777777777777777777777777","expected_size_bytes":140000,"path":"/usr/bin/qstat","platform":"posix","shell_grammar":null},"server_qsub":{"attestation_mode":"server-python-file-v1","deployment_identity":"synthetic-pbs-2024.1","expected_sha256":"6666666666666666666666666666666666666666666666666666666666666666","expected_size_bytes":130000,"path":"/usr/bin/qsub","platform":"posix","shell_grammar":null},"server_remote_shell":{"attestation_mode":"deployment-root-v1","deployment_identity":"synthetic-posix-sh-v1","expected_sha256":null,"expected_size_bytes":null,"path":"/bin/sh","platform":"posix","shell_grammar":"posix-sh-v1"}}}
```

Its exact byte count is `2753`, SHA-256 is
`70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983a`,
and its exact resolved-profile runtime identity is
`{"sha256":
"70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983a",
"size_bytes": 2753}`. Tests construct a current `ServerProfile` with these
exact bytes, call public `resolve_server_profile`, and require that exact
mapping under the fixed logical name before and after snapshot construction.

### Historical bootstrap /1 fixed source and remote-shell grammars

The real trust chain is controller -> exact `mac_ssh` -> Windows OpenSSH
server -> manifest-declared RTwin remote shell -> exact `rtwin_ssh` -> server
OpenSSH server -> manifest-declared `posix-sh-v1` shell -> exact
`server_python` -> exact qsub/qstat or descriptor-relative file operation.
Local `shell=False` removes only an additional controller shell.
The two OpenSSH server services are part of their host OS/deployment boundary,
not caller-selected executables or extra runtime manifest roots; changing their
deployment/security authority is outside this offline contract.

`mac_ssh` and `mac_scp` are opened no-follow and compared with their
manifest path, regular/executable type, size, digest, and deployment-owned
permission conditions before absolute-path structured-argv launch. The
deployment-trusted RTwin shell performs `rtwin-shell-file-v1` for RTwin
SSH/SCP. For `powershell-v1`, manifest strings reject NUL/CR/LF and are
single-quoted with each `'` replaced by `''`. One fixed script sets
`ErrorActionPreference=Stop`, uses `Get-Item -LiteralPath` to reject
containers/reparse links and compare exact length, then
`Get-FileHash -LiteralPath ... -Algorithm SHA256` and ordinal-lowercase digest
equality. It launches the exact path through
`System.Diagnostics.ProcessStartInfo` with `UseShellExecute=false`; the
`Arguments` string is produced only by the frozen Windows CRT encoder already
specified below, and process completion/EOF remain bounded.

`cmd-v1` recognizes only manifest/fixed-launcher tokens matching
`[A-Za-z0-9_:.\\/ -]+`; its deterministic token encoder surrounds each token
with `"` and rejects `"`, `%`, `!`, `^`, `&`, `|`, `<`, `>`,
`(`, `)`, NUL, CR, or LF. The nine-root model intentionally contains no
cmd builtin capable of exact SHA-256 verification of an arbitrary executable.
Therefore a `cmd-v1` deployment parses deterministically but fails
`rtwin-shell-file-v1` compatibility with zero RTwin child invocation. Adding
PowerShell, certutil, a bridge, or another hasher would be a tenth trust root
and requires a new Owner contract; Transport never falls back. This is the
frozen meaning of “if the selected grammar cannot attest safely, fail closed.”

The server shell is exactly `posix-sh-v1`. It has two deliberately separate
encoders with the same byte-preserving single-quote construction:

```text
quote_variable(token) = "'" + token.replace("'", "'\"'\"'") + "'"
quote_bootstrap_source(source) = "'" + source.replace("'", "'\"'\"'") + "'"

command = " ".join([
  quote_variable(server_python), quote_variable("-I"), quote_variable("-S"),
  quote_variable("-B"), quote_variable("-c"),
  quote_bootstrap_source(EXACT_BOOTSTRAP_SOURCE),
  quote_variable(manifest_base64),
])
```

Every variable token rejects NUL, CR, and LF; an empty variable token becomes
`''`. The exact bootstrap source is not a variable token. It permits ASCII LF
but rejects NUL and CR, uses LF-only line endings, and is passed as exactly one
shell word. POSIX single quotes keep embedded LF literal, and a source literal
`'` uses the deterministic close/escaped-quote/reopen sequence above. Decoding
either quoted form reproduces the exact input bytes. No variable value is
concatenated into the quoted source, and source LF cannot terminate the one
quoted shell word or create another command.

The one launcher is exact manifest `server_python` with fixed flags
`-I -S -B -c` and exact source-controlled
`auto-g16-v3-rtwin-bootstrap-v1.py` bytes. That constant is ASCII, begins
`from __future__ import annotations\n`, ends `main()\n`, contains exactly 190
LF bytes and no CR/NUL, has exact size `13904`, and has SHA-256
`056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`.
The implementation test computes size/digest from the exact source constant;
no hand-maintained alternate source or digest is accepted. The earlier
synthetic placeholder digest `b` repeated 64 times with size `2048` and the
prior 12540-byte/170-LF source identity with SHA-256
`724869c6767c1570075812832d57c94e8c9e17ae2d4cd1d9f8781b0796671d2f`
are superseded and must fail runtime-content
closure. This reviewed successor implements only the already-frozen channel
caps and postlaunch attestation. Protocol remains exactly
`auto-g16-v3-rtwin-bootstrap/1` because the AGV3 frame, seven closed schemas,
operation table, and trust semantics are unchanged; any change to those
protocol semantics still requires a reviewed protocol version. The source
reads one
request frame from stdin and writes one response frame to stdout. Both frames
are ASCII magic `AGV3`, one unsigned 64-bit big-endian length, then exactly that
many canonical JSON bytes containing one trailing LF, followed by EOF. The
length counts the JSON bytes including that LF, not the 12-byte header. Request
keys are exactly `binding`, `operation`, `payload`, and `protocol`; response
keys are exactly `operation`, `protocol`, `result`, and `status`. Protocol is
exactly `auto-g16-v3-rtwin-bootstrap/1`, response operation must echo the
request enum, and every accepted response has status exactly `ok`. The table's
`stdin_cap`/`stdout_cap` include the complete header and JSON bytes. There is
one frame, one stdout response channel, and no second binary or authority
channel. Bootstrap-process stderr is diagnostic-only, capped by the table, and
must be empty for an accepted authority response; inner qstat stderr is data
inside the response result. Diagnostics are never parsed as state, job, token,
retry, or scientific authority. Extra frames/bytes, unknown keys/enum/status,
noncanonical JSON, overflow, truncation, nonempty bootstrap stderr, or missing
EOF rejects.

The normative source-quoting fixture is the 12-byte ASCII source represented
as `alpha'\nbeta\n`, with SHA-256
`6053f05b9d4ccfee917933fbaf678ce477573102c2c6b62eaaa3d0290d8dcfb7`.
`quote_bootstrap_source` produces exactly the 18 bytes represented as
`'alpha'"'"'\nbeta\n'`, with SHA-256
`582f76adb6db7219ffaea960e5b01ee95939b0600c002c92d0601199369e9735`.
A POSIX `shlex`-equivalent grammar must decode that complete quoted word to
exactly one argv element whose bytes equal the 12-byte source; zero or two
elements, line-ending normalization, quote loss, or command separation
rejects. The production-source test performs the same one-element byte-exact
round trip for all 13904 source bytes. Replacing any variable token with a
value containing LF/CR/NUL rejects before launcher construction; replacing
the fixed source with CR/NUL also rejects, while LF is preserved.

Binary values use RFC 4648 standard base64 with required padding and canonical
decode/re-encode equality. Tokens decode to `1..4096` bytes. Content decoded
size and lowercase SHA-256 must equal the separately bound fields. Integers are
non-boolean; sizes are non-negative and `effect_sequence` is positive, while
`returncode` is a signed process integer. Every string obeys its frozen lexical
rule. The exact per-operation request schemas are:

| operation | exact `binding` keys | exact `payload` keys |
| --- | --- | --- |
| `ALLOCATE_WORKSPACE` | `transport_store_id`, `store_instance_id`, `runtime_attestation_id`, `attempt_id`, `execution_snapshot_id`, `submission_intent_id`, `remote_workspace` | none (`{}`) |
| `STAGE_EXACT_FILE` | all allocation binding keys plus `workspace_authority_id`, `workspace_physical_token_base64` | `artifact_kind`, `logical_name`, `remote_relative_name`, `sha256`, `size_bytes`, `content_base64` |
| `SUBMIT_QSUB_ONCE` | all stage binding keys plus `prepared_input_artifact_authority_id`, `prepared_input_artifact_physical_token_base64`, `pbs_template_artifact_authority_id`, `pbs_template_artifact_physical_token_base64` | `pbs_basename` |
| `QUERY_SCHEDULER` | all stage binding keys plus `job_authority_id`, `receipt_binding_id`, `remote_effect_receipt_id`, `job_id` | `job_id` |
| `STAT_EXACT_FILE` | all query binding keys | `remote_relative_name` |
| `FETCH_EXACT_FILE` | all query binding keys | `remote_relative_name`, `expected_size_bytes`, `expected_file_physical_token_base64` |
| `RECONCILE_SUBMISSION` | all qsub binding keys | `effect_sequence` |

“All ... keys plus” is exact set union, never optional inheritance. For stage,
`artifact_kind` is exactly `prepared-input` or `pbs-template`; the other fields
equal the current snapshot artifact, and decoded content equals its exact
prepared bytes. For qsub, the two artifact IDs/tokens are distinct, already
persisted under the same workspace, and correspond respectively to those two
kinds. Qstat payload `job_id` equals binding `job_id`. Stat/fetch use the one
exact portable request component. Fetch expected size/token equal the
immediately preceding same-binding stat result. Reconciliation binds the same
workspace and two staged artifacts as qsub and the exact positive receipt
sequence; it never takes a caller job ID.

Field types/cardinality are closed as follows. Every `*_id` is one non-empty
string copied exactly from the already identity-checked snapshot/store/receipt
row named by that field; it is never discovered or recomputed remotely.
`remote_workspace` is one absolute normalized POSIX path equal to the snapshot,
while each basename/logical/relative name is one non-empty portable component
under its existing grammar. Every `*_sha256` is one lowercase 64-hex string.
Every `*_size_bytes` is one non-negative non-boolean integer; stage sizes also
obey the snapshot's stricter prepared-artifact rule. `effect_sequence` is one
positive non-boolean integer. `returncode` is one signed non-boolean integer.
Every `*_base64` is one canonical string; content may decode to zero bytes only
where the bound artifact permits it, while each physical token decodes to
`1..4096` bytes. Every EOF member is the JSON boolean `true`. No field is null,
repeated, optional, defaulted, or accepted under an alias except the two
explicit conditional result schemas below.

The exact successful response result schemas are:

| operation | exact `result` keys and closed values |
| --- | --- |
| `ALLOCATE_WORKSPACE` | `remote_workspace`, `workspace_physical_token_base64`; workspace echoes the request and token is newly created by the trusted agent |
| `STAGE_EXACT_FILE` | `artifact_kind`, `logical_name`, `remote_relative_name`, `sha256`, `size_bytes`, `artifact_physical_token_base64`; semantic fields echo the request and token is the post-write reattested object |
| `SUBMIT_QSUB_ONCE` | `job_id`; one strict normalized PBS job ID |
| `QUERY_SCHEDULER` | `stdout_base64`, `stderr_base64`, `returncode`, `eof_stdout`, `eof_stderr`, `completion_status`; EOF values are exactly `true`, completion is exactly `completed`, and decoded streams remain within 262144/65536 bytes |
| `STAT_EXACT_FILE` | when present: `presence`, `remote_relative_name`, `size_bytes`, `file_physical_token_base64`, with presence `present`; when absent: only `presence`, `remote_relative_name`, with presence `absent` |
| `FETCH_EXACT_FILE` | `remote_relative_name`, `size_bytes`, `sha256`, `content_base64`, `file_physical_token_base64`, `eof`; name/size/token echo the request, token is unchanged after read, digest covers decoded bytes, and `eof` is exactly `true` |
| `RECONCILE_SUBMISSION` | `effect_state`, `job_id` for `confirmed_effect`; only `effect_state` for `confirmed_no_effect` or `possibly_effectful`; states are those exact strings and only confirmed effect carries one strict job ID |

A protocol/operation failure returns no accepted authority frame. In
particular, qsub timeout, lost response, malformed job ID, or any ambiguity is
handled by Execution as possibly effectful/`UNKNOWN`; it is never converted to
an alternate `ok` response or retried. Stat `absent` is a completed exact
observation, not a transport failure. Query's raw nonzero return code remains
data for the existing fixed classifier. Reconciliation does not turn
`confirmed_no_effect` into same-Attempt resubmission authority.

The maximum raw artifact is 134217728 bytes, so its canonical base64 is at most
178956972 bytes. For stage/fetch the header and all fixed non-content JSON are
bounded to at most 65536 bytes; their exact 179306496-byte outer cap therefore
contains the largest legal frame without truncation. Qstat's two inner stream
caps encode to at most 436912 base64 bytes and its 524288-byte outer cap covers
the complete framed result. Other schemas fit their displayed caps. A cap is
checked before allocation, while reading, and at EOF; no truncated response is
ever accepted.

The active identity fixture below supplies four normative canonical JSON
vectors, each shown as its one line; counted bytes include the final LF. The
allocate request is 420 bytes with SHA-256
`dd01886713ad2a41e45ae60ba85fd0a88fa42666d7a9db661c4a0ab2e748fe5e`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"55823409-18d5-5ec8-8cd1-95fc2070fcfa","store_instance_id":"28c10d1a-9f8f-5ce6-84d1-555175c0fcde","submission_intent_id":"intent-1","transport_store_id":"108c8d43-2ea9-5658-9607-ade4cbbeac85"},"operation":"ALLOCATE_WORKSPACE","payload":{},"protocol":"auto-g16-v3-rtwin-bootstrap/1"}
```

Its response is 202 bytes with SHA-256
`ae29cd3e8300a6b90441c431cef7a0d00786c9f5c676ea1a8be6bacdd95f660c`:

```json
{"operation":"ALLOCATE_WORKSPACE","protocol":"auto-g16-v3-rtwin-bootstrap/1","result":{"remote_workspace":"/srv/p/attempt-1","workspace_physical_token_base64":"d29ya3NwYWNlLXRva2VuLXYx"},"status":"ok"}
```

The fetch request is 844 bytes with SHA-256
`4e57b3c5b1a71fc8fdee3ac29c963cf94bcc30c8d64125420388fae9ba6a331b`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","job_authority_id":"51eef369-a569-53e2-8c44-2d22e20057f7","job_id":"123.server","receipt_binding_id":"e824ab64-5fcf-5014-be1a-b53ad70f8cce","remote_effect_receipt_id":"receipt-1","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"55823409-18d5-5ec8-8cd1-95fc2070fcfa","store_instance_id":"28c10d1a-9f8f-5ce6-84d1-555175c0fcde","submission_intent_id":"intent-1","transport_store_id":"108c8d43-2ea9-5658-9607-ade4cbbeac85","workspace_authority_id":"ceff0991-4089-5c97-90b5-199c00467e67","workspace_physical_token_base64":"d29ya3NwYWNlLXRva2VuLXYx"},"operation":"FETCH_EXACT_FILE","payload":{"expected_file_physical_token_base64":"YXJ0aWZhY3QtdG9rZW4tdjE=","expected_size_bytes":19,"remote_relative_name":"job.log"},"protocol":"auto-g16-v3-rtwin-bootstrap/1"}
```

Its response is 341 bytes with SHA-256
`300f841ea40e23c6d03f668b3a5fc9e2fcd2478a20321f870fbe3022a0804e35`:

```json
{"operation":"FETCH_EXACT_FILE","protocol":"auto-g16-v3-rtwin-bootstrap/1","result":{"content_base64":"Tm9ybWFsIHRlcm1pbmF0aW9uCg==","eof":true,"file_physical_token_base64":"YXJ0aWZhY3QtdG9rZW4tdjE=","remote_relative_name":"job.log","sha256":"d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618","size_bytes":19},"status":"ok"}
```

Tests replay all four vectors and reject a missing/extra binding, payload,
result, or top-level key; wrong echoed operation/protocol/status; an illegal
conditional result shape; noncanonical/badly padded base64; a boolean integer;
size/digest/token/EOF mismatch; extra/multiple stdout frames; authority data on
stderr; stdout/stderr/request cap overflow; missing EOF; and fetch bytes that
do not reproduce the exact original content. Thus variable artifact bytes are
closed data, never Python or shell source.

The fixed loader accepts no module name, import path, callback, executable,
argv, source, script, shell fragment, or generic `RUN`, `EXEC`, `SHELL`,
`PYTHON`, or `SCRIPT` operation. After deployment-trusted startup,
`server_python` may compare its own path/size/digest to the manifest to detect
drift and may open/stat/hash exact qsub/qstat paths before structured-argv
launch. None of those post-start checks proves the manifest, remote shell,
server OpenSSH service, OS, or deployment boundary.
