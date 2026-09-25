# Auto-G16 v3 boundary: v31-successors

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V31-PBS-COMPAT-FILE-COMPLETION-01 candidate boundary](v31-file-completion.md#v31-pbs-compat-file-completion-01-candidate-boundary)
- [C4 native controller directory guard proposal](v31-controller-guard.md#c4-native-controller-directory-guard-proposal)

<!-- Moved from docs/v3/boundary-spec.md:5849-5917 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V31 publisher R4 private offline boundary

Owner accepted the exact reviewed R4 package on 2026-09-15 for bounded offline
product implementation. The [frozen Task Contract and provenance](../../publisher-r4/README.md)
close scope, R4 > R3 > R2 precedence, validation and remaining gates. Earlier
publisher hard stops remain for unqualified production; this acceptance permits
the private qualification/tuple/Controller implementation, not target qualification
or activation. Preserve the original synthetic v3 completion and strict behavior.
Approval semantics stay in Controller; Transport reads only fixed deployment
identity evidence. Actual deployment locator and host facts are NOT_ACQUIRED.


### V31 same-Attempt collection recovery boundary

The [accepted C2 delta](../../same-attempt-collection-recovery-contract.md) adds an
Execution-owned submitted snapshot restore and a fixed finite collection path.
Only confirmed SUBMITTED/RUNNING or native terminal replay is admitted; ambiguous
and reconciled submissions are excluded. Original four-store provenance and
original approvals reclose before collection. Old Q qualifies only original
publication source; new collector bytes/imports and continuation are separately
fixed and reviewed. The original window is never extended.

A durable private Observation consumes one remote read epoch before the first
wire operation. It remains in the unchanged full observation-prefix algorithm;
effect receipt sequences remain receipt-only. Complete-bundle/terminal replay
adds no start audit and invokes no wire from process start. No missing-bundle
probe writes an UNKNOWN assessment. Existing collector, capture, guard and Core
reducer own persistence and terminal advancement; no direct state repair.

TP01–TP06 add a local asynchronous heartbeat around only the collection-owned
exact-file fetch. It reports elapsed waiting and final bounded channel facts
without entering the transport I/O/deadline thread. Reporter delay or failure
cannot alter the driver result. The heartbeat is not a receipt, Result, capture
or completion authority; all original wire, identity, timeout and UNKNOWN
semantics remain.

IR01–IR08 admit one private recovery step before a new collection epoch: finish
the exact FETCH already named by the sole latest unmatched successful present
STAT. The repair uses the persisted token and size, retains normal physical/Core
receipts, discards returned bytes and cannot promote the abandoned epoch. A new
full epoch starts only after repair. Ambiguous or multiple prefixes fail closed;
each remote application still consumes a fresh reviewed continuation.

### V31 CREST completion successor boundary

The [reviewed CREST design freeze](../../crest-live-closure-freeze.md) adds the exact
CREST-only version tuple and read-only seed proof consumer. All historical
strict and xTB completion contracts retain their bytes and semantics. No
public Core, Approval, Result or Transport-operation change is authorized.

### V31 exact observed-job recovery boundary

The [delegated recovery delta](../../exact-observed-job-recovery-contract.md) adds only
one fixed observed-job read/proof and narrow reconciled snapshot restoration.
It supersedes the C2 exclusion only for that exact versioned proof. Native
START precedes wire, raw precedes interpretation, original UNKNOWN remains,
and a later collection continuation pins the first recovery authority without
resetting its one-read consumption. No public DDL or producer semantics change.

### V31 CREST short-entry delivery boundary

The narrowly authorized additive delivery tuple is frozen in
[crest-short-payload-contract.md](../../crest-short-payload-contract.md), SP01–SP07.
It retains CREST adapter 3 and completion receipt 2; scheduler 5 declares a short
PBS script plus one exact startup JSON payload. Q3, deployment 3, the fixed
same-process loader and native stage/submit/replay closure own both artifacts.
Old tuples remain distinct. Historical xTB proof compatibility is limited to
[the exact retained bridge generation](../../crest-short-payload-historical-source.md).
Neither inert delivery nor candidate validation grants scientific success.

### V31 Gaussian successor adapter boundary

`auto-g16-v31-gaussian/3` is the base Gaussian successor tuple.
The additive `/4` short-entry and `/5` file-carrier tuples are governed by
[the short-entry contract](../../gaussian-short-entry-contract.md) and
[the file-carrier supplement](../../gaussian-qsub-file-carrier-contract.md).
The base requirements below remain subject to those exact versioned supplements.
It uses the existing public `ProgramExecutionSpec` and
`ProgramExecutionSnapshot` records and the existing private closed adapter
registry. It adds no public record, registry mutation API, Transport operation,
or persistent schema. V30 Gaussian execution remains byte-for-byte independent
and production-usable.

The exact input inventory is one portable `gaussian-gjf` file. Preparation
must parse its UTF-8 bytes and reject NUL/CR bytes, multiple jobs, `%oldchk`,
checkpoint/geometry read dependencies including `Geom=Check`,
`Geom=AllCheck`, `Geom=Checkpoint`, `Opt=ReadFC`, or bare `ReadFC`, missing
charge/multiplicity, missing or non-Cartesian coordinates, and a route that
does not contain the exact closed stage selected by `program_data.stage`
(`opt` or `freq`). Stored `program_data` is exactly
`{stage, completion_mode}` with `completion_mode` equal to
`receipt-on-absence-v1`. The adapter owns no
method, basis, solvent, charge, multiplicity, or scientific default; all such
meaning is already present in the exact input bytes and remains subject to the
normal approval gates.

`ServerProfile` and `ResolvedServerProfile` retain their frozen public shapes.
The profile binds `gaussian_executable_path` and contains one canonical
`v31-gaussian-publisher-qualification-v4.json`; that qualification binds the
real executable `{path,sha256,size_bytes}` and its exact bytes are hash-bound by
the existing `runtime_identities` projection. Snapshot rendering parses the
closed qualification and rejects any mismatch with the spec invocation. The
Gaussian executable bytes themselves are forbidden in `runtime_contents`, and
the qualification digest is never substituted for the executable digest. The
Gaussian qualification and rendering material omit xTB executable and runtime-
data authority. Manifest-v3 remains exactly five roots; public records,
bootstrap protocol and Transport operations do not change.

The closed argv is `[absolute_gaussian_executable]`. The exact bound GJF is
opened no-follow, reattested against its staged identity, and passed as the
child's standard input. Q/4 owns the complete child environment:
`OMP_NUM_THREADS` derives solely from resolved resources; `g16root`,
`GAUSS_EXEDIR`, and `LD_LIBRARY_PATH` must each equal the bound executable's
parent directory; and `GAUSS_SCRDIR` has the sole `attempt-workspace` policy:
the already fresh/no-overwrite Attempt workspace is the scratch directory.
Its existing descriptor chain remains pinned through the
child and is reattested inside final receipt publication, eliminating a second
scratch mkdir/open seam. Workspace replacement or identity drift fails closed.
PATH, HOME, the login-shell environment and any shared `/tmp` scratch are not
inherited.
Required output is exact `gaussian.log`; optional output is
exact `gaussian.chk`. The deterministic receipt-on-absence scheduler renderer writes `gaussian.pbs`,
redirects program stdout/stderr only to `gaussian.log`, records the exact exit
status in an immutable Attempt-local receipt, and adds no caller shell fragment
or ambient lookup. Scheduler terminal state alone never proves completion. Exact
absence may promote only through the same receipt/capture authority: trustworthy
exit zero, stable required `gaussian.log`, and the Gaussian normal-termination
marker produce flow-level `SUCCEEDED`; nonzero or invalid/missing required output
produces the contract-defined `FAILED`; missing, malformed, unstable or
untrusted evidence remains `UNKNOWN`. No branch authorizes automatic retry or
scientific acceptance.

The renderer embeds `v31-completion-rendering-material/5`. The same fixed tuple
is admitted by collection and reconciliation restoration only for the exact
already submitted Attempt under its production Project journal. Restore does
not allocate, stage, submit, retry, replace the Attempt, or reinterpret prior
UNKNOWN evidence.
