# Auto-G16 v3 acceptance: v31-successors

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V31-PBS-COMPAT-FILE-COMPLETION-01 candidate acceptance](v31-file-completion.md#v31-pbs-compat-file-completion-01-candidate-acceptance)

<!-- Moved from docs/v3/acceptance.md:2092-2154 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V31 publisher R4 offline acceptance

Owner accepted the exact reviewed R4 package on 2026-09-15 for bounded offline
product implementation. The [frozen Task Contract and provenance](../../publisher-r4/README.md)
close scope, R4 > R3 > R2 precedence, validation and remaining gates. Earlier
publisher hard stops remain for unqualified production; this acceptance permits
the private qualification/tuple/Controller implementation, not target qualification
or activation. Preserve the original synthetic v3 completion and strict behavior.
Approval semantics stay in Controller; Transport reads only fixed deployment
identity evidence. Actual deployment locator and host facts are NOT_ACQUIRED.


### V31 same-Attempt collection recovery acceptance

The [frozen C2 CR01–CR10 matrix](../../same-attempt-collection-recovery-contract.md#8-incremental-acceptance-and-validation) owns new recovery acceptance.
CR01–CR09 require proportional offline evidence, including actual process exit,
exact submitted restoration, new-window/old-Q separation, full wire preparation,
mutation tripwires, four-store drift, native guard contention and crash/replay.
Old FC/C4/P01–P08 evidence keeps its original candidate binding. CR10 is separate
same-job native collection and independent readback under a concrete reviewed
installation; offline PASS grants no live or scientific acceptance.

For a long same-job output fetch, TP01–TP06 additionally require an
off-transport-thread progress reporter, collection-owned FETCH-only selection,
no sensitive/path/content fields, and unchanged driver tuples when reporting
blocks or fails. These checks supplement CR10 and cannot replace complete file
identity, hash, restat, receipt, capture or replay evidence.

IR01–IR08 additionally require focused interrupted-prefix evidence: exactly one
unmatched successful present STAT can drive only its already determined FETCH;
zero needs no repair, while multiple, absent, malformed, conflicting or unowned
prefixes reject before wire. A successful repair is retained as an ordinary
receipt but its bytes are not completion evidence. The following new epoch must
still perform the complete original declaration sequence and reach the existing
bundle, final-absence, replay and Core-transition gates.

### V31 CREST completion successor acceptance

Apply the [frozen CREST criteria](../../crest-live-closure-contract.md) and its
[delegated design acceptance](../../crest-live-closure-freeze.md). Required evidence
separates immutable compatibility, offline adversarial closure, current
qualification, exact approval, one execution, native capture/replay and
independent chemical integrity. Historical xTB evidence is not CREST evidence.

### V31 exact observed-job recovery acceptance

Apply RF01–RF10 in the externally hash-bound normative contract identified by
[the recovery delta](../../exact-observed-job-recovery-contract.md). Offline evidence
must exercise crash/no-second-read, concurrent owners, full native fresh-process
restore/capture/replay, preserved UNKNOWN and wrong-job receipt rejection.
A synthetic native-chain pass does not qualify the new remote seam or accept
real outputs. Parent-owned qualification and exact application remain separate.

### V31 CREST short-entry delivery acceptance

Apply SP01–SP07 in [the frozen contract](../../crest-short-payload-contract.md).
`tests/v31/transport/test_crest_startup_payload.py` owns the incremental tuple,
loader refusal, same-process exit, native dual-stage/submit, installation P09,
collection/replay and retained historical-source evidence. Adjacent existing
owners cover unchanged completion, approval and bridge boundaries. Retain exact
candidate/run identities and independent review; target production-loader P09
and a fresh precisely approved real CREST Attempt remain separate live evidence.
No old UNKNOWN Attempt or 703 inert success is promoted by these tests.

### V31 Gaussian successor adapter acceptance

The narrow Gaussian successor is accepted offline only when all of the
following hold:

1. The base `gaussian` tuple is `auto-g16-v31-gaussian/3`; the additive `/4`
   and `/5` tuples must satisfy [the short-entry contract](../../gaussian-short-entry-contract.md)
   and [the file-carrier supplement](../../gaussian-qsub-file-carrier-contract.md).
   Unsupported versions and
   direct construction fail closed, and the xTB/CREST serialized semantics and
   adapter tuples are unchanged.
2. Exact valid Opt and Freq Cartesian GJF inputs close deterministically into
   one spec and snapshot. The executable absolute path, size and SHA-256 must
   equal the exact executable identity inside the canonical Gaussian
   qualification, while the absolute path also equals the resolved profile path.
   The qualification bytes are profile-hash-bound; their own digest is never
   treated as the executable digest. Putting Gaussian executable bytes in
   `runtime_contents` rejects.
3. Multiple Link jobs, non-UTF-8/NUL/CR inputs, `%oldchk`, `Geom=Check`,
   `Geom=AllCheck`, `Geom=Checkpoint`, `Guess=Read`, `Opt=ReadFC`, bare
   `ReadFC`, missing charge/multiplicity, missing or malformed Cartesian
   coordinates, and route/stage mismatches reject before any effect.
4. Stored program data has exactly `stage` and `completion_mode`, accepts only
   `opt` or `freq`, and fixes completion mode to `receipt-on-absence-v1`.
   Caller argv, command, stdin, environment and output declarations cannot be
   injected.
5. The exact scheduler bytes use the resolved resource values, invoke only the
   bound absolute executable, pass the no-follow exact GJF as stdin, require
   `gaussian.log`, and
   declare only optional `gaussian.chk`. Input, output and scheduler names are
   collision-free. Completion uses exact absence plus the bound Attempt-local
   receipt and stable capture: exit zero and the Gaussian normal-termination
   marker are required for flow-level success; scheduler terminal state alone or
   missing/untrusted evidence remains `UNKNOWN`, and no branch grants scientific
   acceptance.
6. Q/4 accepts only the closed environment keys `g16root`, `GAUSS_EXEDIR`,
   `LD_LIBRARY_PATH`, and `GAUSS_SCRDIR`; the first three equal the executable
   parent and scratch policy is exactly `attempt-workspace`. The already
   fresh/no-overwrite Attempt workspace remains descriptor-pinned through
   final receipt publication. PATH, HOME, ambient variables, shared `/tmp`,
   declaration drift and workspace replacement reject.
7. Focused preparation, identity/rebuild, snapshot, staging, at-most-once,
   terminal capture and adversarial tests pass. Existing xTB/CREST focused
   tests pass without changed historical vectors.
8. Same-Attempt collection and reconciliation restore material/5 without a
   second stage or submit, then use scheduler absence, receipt and stable
   capture normally. Wrong tuple, job, Attempt or authority rejects.
9. Static CI-contract and sensitive-data scans pass and a findings-first
   review reports no open P0/P1. Offline PASS grants no target qualification,
   installation, live operation, scheduler-success substitute, result parsing,
   scientific validation, or scientific acceptance.
10. `ServerProfile` and `ResolvedServerProfile` keep their frozen public shapes.
   The closed Gaussian qualification binds only deployment, server-Python and
   the exact Gaussian executable; it requires no xTB executable or runtime-data
   authority. Qualification mutation changes the existing profile identity,
   executable mismatch rejects snapshot rendering, manifest-v3 retains exactly
   five roots, and historical profile identities remain structurally unchanged.
11. The Gaussian `/4` submit effect preserves the qualified bootstrap's exact
    30-second qsub child deadline and uses a 120-second controller wait, leaving
    a separately asserted 90-second budget for pre-submit checks, atomic carrier
    receipt persistence and response transport.  The generic operation table,
    qualified bootstrap bytes and xTB/CREST waits remain unchanged.  Timeout or
    missing receipt stays `UNKNOWN`, never authorizes a second submission, and
    never becomes completion evidence.
12. The exact file-carrier contract digest matches
    `docs/v3/gaussian-qsub-file-carrier-contract.md`. The submit owner publishes
    the carrier, final entry and qsub invocation-start records as no-replace
    0600 pending/final hard-link pairs before the sole qsub call. The final
    entry is derived only from the immutable reviewed template and embeds the
    exact carrier descriptor. The loader retains and validates both names,
    binds the carrier's canonical SHA-256 and physical identity to that embedded
    pin, and rejects coordinated same-byte carrier/start replacement before its
    first stage.
    qsub uses the exact direct `-d/-l/-q/gaussian.pbs` vector with no `-v` or
    `-V`. Success, returned failure and timeout/interruption each preserve a
    `/2` post receipt when the server process can durably publish it; missing
    durable evidence remains `UNKNOWN`. Offline evidence includes single-submit
    and no-retry checks and does not qualify or install changed source bytes.
    This behavior is an additive Gaussian adapter `/5` tuple (Q6, material
    `/7`, scheduler `/8`, prebinding `/8`, deployment-v6). The historical `/4`
    Q5 tuple remains decodable and replayable with its original exact bytes.
