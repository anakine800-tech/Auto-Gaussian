# Auto-G16 V31 file completion freeze dossier

Task: `V31-PBS-COMPAT-FILE-COMPLETION-01`; feature development / v3 /
OWNER-GUIDED / ordinary isolated Codex app task.

## Identity and authority

- Remote: `https://github.com/anakine800-tech/Auto-Gaussian.git`.
- Remote default `refs/heads/main`, queried read-only on 2026-09-14.
- Base/initial HEAD: `6b2ece4443951381f0206c93e55e581ca175dd5e`.
- Base tree: `b73933008a2560a3b6f4e093bac26611e4b187de`.
- Unique branch: `codex/v31-pbs-compat-file-completion-01`.
- Physical linked worktree: Codex app worktree slot `2e44`; exact local path
  is retained in the task tool evidence, not published as machine metadata.
- Initial tree was clean. Original shared checkout was not modified.
- User authorized contract-first candidate, necessary independent review,
  local freeze commit and conditionally later offline implementation.
- Push/PR/merge/deploy/release/live/cleanup/scientific acceptance: no authority.

## Candidate C1 content manifest

These six files define the proposed normative candidate. This dossier records
its hashes externally to that set to avoid a self-hash cycle. Dossier updates
do not purport to change the reviewed authority bytes. The local candidate
commit additionally binds the exact dossier and all six files.

| File | SHA-256 |
| --- | --- |
| `OWNER_DECISIONS.md` | `cce94bb4e3908f8d467824f0e2af4feeec17634871fd827e47b7431dc6de9fec` |
| `docs/v3/boundary-spec.md` | `5971f17f6006b5a914b1f96238fd96c6ec76f5a0967ca207eefad0a77462e8e6` |
| `docs/v3/acceptance.md` | `6e163694281d90691a906160b5b55e7fdea54c773c3fc7dafe6910b24662bbcc` |
| `config/context-map.toml` | `7f2b1f6335bb78385a501ef63c87eb921171eb8ed54d4715799eda3c447f6024` |
| `docs/v3/AUTONOMOUS_DEVELOPMENT.md` | `54464e5bffa7bba227905e70f2c88a38df889fe1037d9bd87a1aecf414c893e9` |
| `docs/v3/STATUS.md` | `cfeff841cd5d7f14204132698339d0ae2b8e466b2db91f186797bc001ed0fca3` |

## Review and freeze disposition

- Author: this task; author review is not independent review.
- Independent preflight source audit: subagent `contract_seam_audit`; checked
  current runtime/Transport seams, reported required contract closures. It
  did not review this candidate or issue a freeze PASS at that stage.
- C1 independent technical review: REQUEST CHANGES; three P1 and three P2.
  Reviewer `contract_seam_audit` independently verified all six C1 hashes.
  P1: no durable capture bytes; assessment/advance concurrency gap; ambiguous
  post-link publication failure. P2: incomplete epoch/proof identity;
  unspecified publisher qualification ingestion; zero-rc missing-output path.
  C1 remains historical; it is not the implementation candidate.
- C2 addresses that complete finding set in one revision. It freezes a closed
  private Core Result byte bundle, exact epoch/prefix/proof fields, physical
  nonblocking writer guard and link linearization point. Required absence is
  explicitly recorded even at rc=0. Production receipt mode is hard-disabled
  until a later exact qualification contract/gate, with no boolean override.
- Exact C2 independent technical re-review: PASS by subagent
  `contract_seam_audit`, 2026-09-14. Reviewer independently recomputed all six
  C2 hashes and checked the current diff against the base. All three C1 P1
  and three C1 P2 findings closed; no new P0/P1/P2 was reported. Review is
  contract technical evidence only, not repository Owner approval.
- Review evidence locations in C2 boundary: durable bytes 5390–5429;
  shared writer guard 5465–5489; link publication point 5316–5332;
  production hard stop 5266–5278; zero-rc absence 5311–5314. The task's
  independent subagent final response retains the full findings and hashes.
- Repository Owner L3 review / exact-candidate acceptance: PENDING.
- Status: CANDIDATE, NOT FROZEN FOR IMPLEMENTATION.
- Product implementation: NOT STARTED; no product/test/schema bytes changed.

## Validation and next gate

Editing preflight `./scripts/python core scripts/dev_preflight.py --require-clean`
passed at clean base after unique branch creation. On exact C2 authority
bytes, TOML parsing, five new context anchors, six manifest SHA-256 checks,
`git diff --check`, `./scripts/python core scripts/static_quality.py` (23
selected Python files / 4 rules), `scripts/audit_ci_contract.py --json` (five
required contexts / no errors or warnings), and `scripts/audit_python_contract.py`
passed. `./scripts/python check --profile core` verified Python 3.13.13.
The Python/static audits describe existing unchanged code/declarations, not
receipt implementation. No product test count is claimed. Candidate selection
requires a commit and is recorded in the final handoff after this local commit;
no product/full suite is launched as a selector side effect. No complete full
suite, remote CI, production qualification or live success is claimed.

The concrete Owner decision is acceptance of the exact candidate's publisher
trust model (existing qualified trusted-bootstrap/same-UID exclusion),
absence-only final reduction with terminal contradictions held UNKNOWN, and
structural output closure separated from scientific acceptance. Independent
technical findings must close before presenting this decision. A freeze grants
only the already bounded offline phase, never any operational authority.

Implementation handoff is the phase-2 exact path list and FC01–FC15 in the
Task Contract/acceptance document. Reuse existing pre-qsub marker and private
STAT/FETCH; preserve historical strict bytes and public record budget. If an
additional path/protocol/public record is needed, stop for a precise delta.
Worktree and branch remain retained; cleanup is PENDING / not authorized.

## Candidate C2 content manifest

C2 supersedes C1 only as the current review candidate; Owner freeze remains
pending. These are the exact authority bytes for re-review.

| File | SHA-256 |
| --- | --- |
| `OWNER_DECISIONS.md` | `cce94bb4e3908f8d467824f0e2af4feeec17634871fd827e47b7431dc6de9fec` |
| `docs/v3/boundary-spec.md` | `a409805944bd93951d17e1920fa42348f9e373df6cc5b64505a49abab3d3560f` |
| `docs/v3/acceptance.md` | `8faedbf71b11eb86a5180e0ab57db510db8387811bb9175a83a80e66d08ed189` |
| `config/context-map.toml` | `7f2b1f6335bb78385a501ef63c87eb921171eb8ed54d4715799eda3c447f6024` |
| `docs/v3/AUTONOMOUS_DEVELOPMENT.md` | `87e2404823c4e7cd15ff3c43df706c32bfa34abaee469b40942d05c20b258bd2` |
| `docs/v3/STATUS.md` | `ccaab050ef456a42992a457b7ceb51b651ec7609b06f4d9b719a1894f8d76245` |

## Exact Owner review request and local disposition

C2 is technically reviewed and content-bound, **not Owner-frozen**. Accepting
C2 would activate only the Task Contract's proposed offline phase in this same
isolated worktree. The concrete choices are existing trusted-publisher/same-UID
threat-model exclusions, no-replace link publication with local durable byte
capture, absence-only completion with explicit conflict/UNKNOWN handling,
structural output closure independent of science, and initial synthetic-only
implementation with production receipt mode hard-disabled. No real publisher
qualification artifact or operational approval is implied.

Handbook section 7 requires repository owner review for L3 scheduler/security
work; that review has not yet occurred on these new bytes. This is the sole
contract-freeze blocker after C2 technical PASS. No product implementation,
remote publication/integration or original shared-checkout mutation occurred.

## Owner C2 activation — 2026-09-14

Following the exact C2 review request, the repository Owner replied “确认”.
This accepts the six C2 hashes above at commit
`3ea04da8bc0a401920d721adac7649d5d7af88ab`, tree
`ca4ca0ce7407657a650a3905c18fd5fb79be7269`, including initial synthetic-only
implementation and production publisher hard stop. C2 is now FROZEN FOR THE
BOUNDED OFFLINE IMPLEMENTATION. Earlier PENDING/CANDIDATE statements record the
pre-acceptance state; this explicit activation closes them without changing
the six reviewed authority files. The Task Contract's phase-2 allowed paths
are active in this same task/worktree. All operational/publication prohibitions
remain. Implementation and FC01–FC15 validation are pending, not accepted by
this contract approval.

## C3 implementation-discovered P1 and candidate

After C2 activation, read-only interface inspection established that
ResolvedServerProfile drops manifest bytes (models.py:534–559), while the
snapshot builder and identity replay have no separate source for their
contents (program.py:1043, 1202–1258). Existing Transport driver state is later
and cannot supply this input without a new dependency. The independent
reviewer explicitly acknowledged this seam was missed in the earlier C2 PASS.
C2 Owner acceptance is retained; dependent renderer is STOPPED, not repaired
by assumption. The proposed C3 supplement supplies a closed profile-verified
material input embedded as data in the existing scheduler bytes. Public record
shapes and the production hard stop remain unchanged.

Before the gap was confirmed, initial pure receipt serialization/structural
output-check work began in `_program_completion.py`; it has no runtime callers,
no completion-state/effect authority, and is incomplete. Syntax validation is
not FC01–FC15 completion. It is retained separately from the contract manifest.

C3 technical review: PASS by independent subagent `contract_seam_audit`.
The reviewer recomputed all six hashes below, checked the diff against
`3ea04da8bc0a401920d721adac7649d5d7af88ab`, and reported no P0/P1/P2 in C3.
The missing-material P1 is closed in this candidate, pending Owner acceptance.
C3 exact Owner acceptance: PENDING; dependent renderer remains paused.

### C3 authority-file content manifest

- `OWNER_DECISIONS.md`: `96eafc99792963f524770242d6057c2727b63b9a6bd479c9b0455729e0021585`
- `docs/v3/boundary-spec.md`: `ccd97a66b320ef2a87e12b5b54b7e437bf167c7cb5eb205e2d7c033e959aea98`
- `docs/v3/acceptance.md`: `26535be459b45911aea17a886948fbcfe1acb18ecd94b112b33238cebfcac271`
- `config/context-map.toml`: `7c6ada260ff777118c690971278986f6c2966db294a004619069adad63b98572`
- `docs/v3/AUTONOMOUS_DEVELOPMENT.md`: `6c309be1e58924ecfe38bf1ff44722f682e5a74f26b7aa9550a52ce48f1539e6`
- `docs/v3/STATUS.md`: `2535821d2b34cc31d3adbb17bfe84d4f5a15dc19b055b5cf84936a8d17cb781d`

### C3 checkpoint validation and retained WIP

C3 TOML/routes/hash/diff checks and the CI declaration audit passed locally.
The unconnected `_program_completion.py` is not included in this documentation
commit or in the C3 review PASS. Its syntax and 16 standalone grammar/output
checks passed at 2026-09-14T09:07:32Z (0.014 seconds), without any snapshot,
publisher, capture, runtime completion or scientific claim. All FC01–FC15 and
C3 implementation vectors remain pending. This task owns the untracked WIP;
no unrelated changes were present and no cleanup was performed.

Retained WIP SHA-256: `aa235ef7d380ce774cba08f4163a3c8cab48dee7433527658d56250e32b67f5b`.

## Owner C3 activation — 2026-09-14

The Owner replied “确认” to the exact C3 material-derivation request after its
independent technical PASS. This accepts the six C3 authority-file hashes at
commit `6b613026d1eb715fa4b235f57044c652d81f37aa`, tree
`47855dcad48a7b1a6efc27e0f5b0d2e444036080`. C3 now supersedes C2 only for the
explicit private material/data-line/prebinding delta. Dependent offline
implementation may continue within the unchanged allowed paths. Earlier C3
pending/stopped statements are historical checkpoint evidence. Production,
publication, deployment, live actions and scientific acceptance remain outside
authority. No implementation acceptance is inferred from this approval.

## Phase-2 offline implementation checkpoint — 2026-09-14

C2/C3 activation is unchanged. The six authority-file hashes above were
recomputed at 10:24 UTC and remain exact. This checkpoint implements only the
allowed private xTB version-3 path: profile-closed rendering material and fixed
wrapper, fresh-Attempt mode, dual-source file acquisition, durable raw-byte
Result bundle, complete-prefix assessment/replay and separate private `/2`
proof. Production driver construction and evaluation remain hard-disabled with
`publisher-not-qualified`; strict `/1` consumers reject receipt mode.

The wrapper retains the workspace ancestor descriptor chain, reattests it at
write/launch/publication boundaries, accepts only profile-bound runtime data
components (including the mandatory `.param_gfnff.xtb`), binds the program log
to the actual stdout/stderr inode, and uses exclusive pending plus no-replace
hard link. No real wrapper/program invocation or Linux publisher qualification
has occurred. Full wrapper control-flow tests replace Popen, subreaper and
wait with inert fixtures; source/mechanical tests are not kernel evidence.

### Implementation review corrections

Independent reviewer `contract_seam_audit` found four P1 and one P2 in the
first wrapper/material WIP: mandatory runtime dotfile rejection; unretained
workspace parent descriptors and late reattestation; missing actual log inode
binding; material validation after provisioning attestation; and manifest text
grammar weaker than the extracted baseline. Those findings were addressed in
the candidate, with bounded regression vectors.

The second WIP review found one P1 and two P2: a new capture or null-result
UNKNOWN could hide earlier accepted file drift/missing bytes; private bundle
sizes and assessment evidence references were incompletely closed; unlock or
close exceptions could retain the in-process guard. The candidate validates
all accepted bundles against both their original prefixes and all current
later evidence, checks exact integer sizes and provenance IDs, and releases
the in-process guard in an outer finally. Final independent review disposition
is recorded separately below; these fixes are not self-issued review PASS.

### Native controller guard blocker

The required guard remains a retained no-follow descriptor and nonblocking
exclusive flock on the existing ProgramTransportStore database inode. An
isolated local macOS experiment observed `sqlite3.OperationalError: database
is locked` for both default and unix-posix VFS when SQLite read/write followed
the required flock; unix-excl failed to acquire flock. No repository database
was used by that experiment. Product code does not switch VFS, create a lock
sidecar, disable SQLite locking, add a qualification override or retry. It
maps the incompatibility to a boundary rejection and releases owned resources.

On Darwin only, completion model tests inject a test-local flock substitute;
they exercise evidence logic and contention modeling, not native positive
locking qualification. A separate test restores the real flock and verifies
boundary rejection with zero driver calls and zero epoch writes. No compatible
local Docker/Podman/Colima/Lima executable was available. No environment was
installed and no remote host or CI was started. A user question about an
existing compatible local environment remains separate from any authorization
to connect or execute there.

**Native guard plus SQLite positive/cross-process evidence: BLOCKED /
NOT ACQUIRED. Complete FC13 and full phase-2 implementation acceptance are
not closed.** A compatible authorized local environment could supply the
missing evidence without changing the contract. Treating mock-only coverage
as full acceptance or changing the locked object/locking design would require
a new explicitly reviewed contract decision; neither is inferred here.

### Frozen implementation content

| Allowed file | SHA-256 |
| --- | --- |
| `auto_g16/execution/program.py` | `ec842f9e480a01c7d60bce8e4da2a6f1c12f0138fb59ba813f818c82ba6ae998` |
| `auto_g16/execution/program_runtime.py` | `78c213c07dbde105a52bb7292d82d04f6515f8a8200d0e05e35a93db1b4a8dba` |
| `auto_g16/execution/_program_completion.py` | `9bac5072e08a90781434b5d23564f1979d4d2fef3b09808f1119d8c385a22fe1` |
| `auto_g16/execution/_program_completion_wrapper.py` | `00623071507c37dda0460105130b3fb182c5f856ac106e015a9e1ee812605e37` |
| `auto_g16/transport/program.py` | `af369d5177c9ed4cefed17b50274038fa7528d9d77c5df588bec3508eb3ce986` |
| `auto_g16/transport/_program_rtwin.py` | `a0ac8552bc8f2d427f40b91a02881fd6a9c1d556aa179a475a1ab1be3d4c10eb` |
| `tests/v31/transport/test_program_completion.py` | `05678a46a7a0e8b9b4af086ecd53267e53f45f87894aaa807dcb90b41c3f2d05` |

### Validation scope

Preflight passed with only the owned dirty-candidate warning. Syntax, diff,
CI declaration and Python contract audits passed. The progressive configured
static check passed (23 existing selected files); separately applying the same
four rules to all six changed product modules and the embedded wrapper found
zero violations. Inert test code intentionally evaluates the fixed wrapper
source and is not represented as passing the product no-eval/exec rule.

Focused runs passed 46 new completion tests and 185 adjacent strict composition,
RTwin bridge and Lane-A tests before the last three source/consumer vectors
were added. A final bounded combined run of the 49 completion tests plus those
185 adjacent tests is recorded below. It is not full repository validation,
remote CI, native positive guard evidence or scientific acceptance. No shared
checkout, historic job/evidence or Core/public schema was changed.

### Final review correction: safe absence after open

The first frozen implementation candidate above passed the bounded combined
run: **234 tests, 86.223 seconds, OK** (49 completion and 185 adjacent tests).
Independent frozen-source review nevertheless found one residual P1: output
collection caught FileNotFoundError around the whole read, so ENOENT from a
post-open named metadata recheck could be encoded as absence. The same branch
could accept disappearance of the wrapper-created log after close. The review
reproduced the post-open case using only an inert temporary file and injected
metadata failure; no program was invoked. This candidate was REQUEST CHANGES,
not a code or acceptance PASS.

The final delta changes only the wrapper source and completion tests. A
private AbsentFile exception now denotes exclusively the initial no-follow
open's ENOENT. All failures after a successful open stop publication, and the
already created log may never become an absent output. Negative vectors cover
post-open named metadata ENOENT and log disappearance after close, including
no receipt and at most one inert launch. The two hashes below supersede only
the corresponding entries in the preceding implementation manifest:

- `auto_g16/execution/_program_completion_wrapper.py`:
  `664e6ea75ac2b9e1b7d880e198b5a41b195054f54d956548fa8e0ce5c2e6ba09`
- `tests/v31/transport/test_program_completion.py`:
  `764fd4ee081c2bbf4d3b98526efa265a16fb8d4da1d518ade63543a0d468ea83`

All other product and authority-file hashes remain unchanged. The final delta
is limited to receipt-mode wrapper semantics, so the 185 passing adjacent
strict/bridge/Lane-A vectors are retained; the full completion module is rerun
for the changed source. Independent delta review and the final run are
recorded below. The native guard/SQLite blocker is unchanged.

### Final bounded disposition

- Final completion-module run: **50 tests / 48.025 seconds / OK** on the
  final two hashes. Native Darwin positive locking was not substituted into
  this claim; the real rejection test and test-local lock model remain explicit.
- Final independent delta review by `contract_seam_audit`: residual P1 CLOSED;
  no new P0/P1/P2 identified. The reviewer independently recomputed the final
  wrapper/test hashes and confirmed the other five product hashes unchanged,
  and ran the two affected inert tests successfully. Combined with the earlier
  frozen-source review, no residual code finding is identified in the reviewed
  scope. This is not a complete FC01–FC15 acceptance or Owner/production PASS.
- Local staged inventory contains only the six allowed product files, one
  allowed new test and this dossier. The sensitive/private-key/token/private
  local-path scan has zero findings. No Core schema, public record inventory,
  bootstrap protocol or historical strict serializer was edited.
- **Disposition: OFFLINE IMPLEMENTATION CHECKPOINT; BLOCKED ON NATIVE GUARD
  POSITIVE EVIDENCE / FULL FC13.** Retain the isolated branch/worktree. No
  publication, integration, deployment, live execution, resubmission, cleanup
  or scientific acceptance is authorized or performed. No lock redesign,
  mock-based acceptance relaxation or C4 decision is inferred.

### Local commit and validation-selection stop

The code/evidence checkpoint was committed locally as
`9c4946357483055552dd464d6debb6707430e3e6`, tree
`11c0d88348582be79854bbd5c7c075132f494f4f`. Normal pre-commit hooks passed;
no hook was disabled. The clean-tree preflight, CI declaration audit and
Python contract audit then passed. No remote CI or protection claim follows.

The exact-base validation selector was run with base
`6b2ece4443951381f0206c93e55e581ca175dd5e` and that complete HEAD. It returned:

- `schema`: `auto-g16-validation-selection-result/2`;
- `manifest_blob`: `2d328bc6feae9c858b721406c48034a73cd99a60`;
- `fail_closed`: **true**;
- fallback `lane`: `legacy-release`; `tests`: empty;
- reason: `selected tests do not carry required safety evidence: approval-owner-separation`.

Read-only inspection identifies the interaction: v3 control documentation
selects the v3-full lane, which replaces selected route tests with the
manifest's v3_full_tests list. Execution/Transport routes still require
approval-owner-separation evidence, but those carriers are absent from that
list. Both selector and validation-selection manifest are unchanged from the
approved base and outside this task's allowed mutation paths. Passing focused
tests does not override the failed selection contract. No fallback full run,
route weakening, extra-scope repair, remote CI or new user task was started.

The final disposition therefore has **two independent blockers**: native
controller guard positive/full FC13 evidence, and the validation-selection
safety-carrier configuration. The isolated offline code checkpoint is retained;
full implementation/integration acceptance is not claimed. Resolving the
selector requires separately bounded authority for its owning configuration
or implementation; this evidence-only note grants none.

## Authorized blocker follow-up A/B — 2026-09-14

The Owner authorized continuation in this same isolated task from clean
checkpoint `502175664ff86185434d8e4a1ba4df4975b52112`, tree
`d156782a6210b3a49fee616f855d61602943d788`, through the parent task. Scope A
adds only `config/validation-selection.json` and
`tests/test_validation_selector.py` plus necessary evidence records to the
allowed mutation paths, to restore existing safety carriers without changing
the selector, runner, workflows, required checks or fail-closed semantics.
Scope B authorizes local credential-free native probes, a C4 candidate in the
six phase-1 authority documents and this dossier, and independent technical
review. It does NOT accept a not-yet-written C4 design or authorize its product
implementation. C2/C3 and all production/publication/live/cleanup prohibitions
remain active. Necessary local checkpoint commits and normal hooks are allowed.
No new task, BUS CTRL, historical Issue change or automatic full run follows.
Clean preflight passed before this follow-up's edits.


### A safety-carrier repair — bounded validation and review

The manifest retains its original three v3_full_tests and adds only seven
existing carriers: tests.test_execution_authorization,
tests.test_live_approval_effect_time_replay,
tests.test_direct_one_hop_transport,
tests.test_legacy_descriptor_mutation_capability,
tests.test_legacy_root_authority_contract,
tests.test_direct_qstat_acquisition and
tests.test_resource_monitor_efficiency. These close the complete declared
safety-tag inventory without changing routes, selector, runner or required
checks. Removing any added carrier still fails closed.

Changed-byte SHA-256:

- `config/validation-selection.json`:
  `5a9d7ebd4f4d6823f1f82bcd6a3042ffe164a142f4ab9fc7589d0f7dcb1fa469`;
- `tests/test_validation_selector.py`:
  `5e4033283754983796858ba92af303e78cdfeac2690e4b87ba93b14c4130ff05`.

Validation on these bytes, core Python 3.13.13, 2026-09-14 UTC, no coverage
modifiers:

- `./scripts/python core -m unittest tests.test_validation_selector -q`:
  **86 tests / 43.519 seconds / exit 0 / OK**, no skipped tests. Two earlier
  test-authoring failures expected a generic reason string; assertions were
  corrected to the unchanged selector's exact self-protection reason before
  this final run. Do not count the earlier failed run as evidence.
- `./scripts/python core -m unittest` followed by the seven added carrier
  module names above and `-q`: **150 tests / 436.567 seconds / exit 0 / OK**,
  no skipped tests. Expected synthetic error output is negative-vector
  evidence, not real live commands. This is a bounded carrier run, not full
  discovery. Exact start timestamps were not separately retained; runner
  totals/durations and tool completion evidence are retained.
- Independent A review by contract_seam_audit: no P0/P1/P2. Reviewer recomputed
  both hashes and independently ran all five added selector tests
  (**5 / 1.397 seconds / OK**). The real clean-Git fixture binds base/head/tree
  and manifest blob, proves ordinary mixed docs/Execution/Transport routes
  carry all required safety tags, and separately preserves manifest/test
  self-protection.
- Static CI/Python declaration audits and diff check passed. No remote CI or
  branch-protection claim follows. The native guard/full FC13 blocker remains.

Actual A changes intentionally touch self-protecting manifest/test bytes.
Exact-HEAD selection must therefore still fail closed to legacy-release with
empty tests and reason `selector, manifest, runner, or selector-test bytes
changed`. This is distinct from the old missing-safety-carrier error: the
mixed-route fixture closes that defect, while A cannot bypass its own safety
escalation. No automatic full run or integration acceptance is authorized.


### A local checkpoint and C4 proposal evidence

A was committed with normal passing pre-commit hooks as
`6c6c982af4289f74180d5fbeb5c4cf90ce10778a`, tree
`d0d9a3fc64867ae13bc7de330db63663c90af636`. Staged inventory was exactly the
two authorized configuration/test files and this dossier; sensitive/private-
key/token/private-path scan had zero findings. Six C4 proposal docs remained
owned unstaged work, so this was not advertised as a clean whole-worktree
handoff. No product file or completion test changed from checkpoint 5021756;
all seven frozen product/test SHA-256 values were independently rechecked.

#### C4 native feasibility probes

Credential-free local retained temporary files only; no product implementation,
real program, service, network, installation, VFS change or artifact deletion.
Observed environment: Darwin/macOS 26.6.2, Python 3.13.13, SQLite 3.53.1,
default sqlite3 connections on the native temporary volume. Filesystem type
identification was NOT_ACQUIRED; no general APFS, network-mount or Linux
qualification is claimed. Temporary artifact locations remain in local tool
evidence, not versioned private machine paths.

The directory probe's canonical recorded JSON file SHA-256 is
`50a2833a90745837b57533153770650093cebafdb90ce3c4a65a326c4deba102`.
All **14 expected observations** were true:

- Default SQLite two-connection read/write succeeds while its existing parent
  directory has real EX|NB flock; an independent process is busy, including a
  process launched by another thread, and a same-process second FD is busy.
- Closing an unrelated descriptor or a duplicate FD retains the original
  lock; re-flock of the same FD succeeds, demonstrating why the private token
  policy is necessary. Explicit release allows a new process to acquire.
- A controlled inert holder exits through os._exit(77); it blocks contenders
  before death and permits a new explicit acquisition afterward.
- O_NOFOLLOW rejects a directory symlink, and a deliberately hardlinked inert
  database exposes nlink=2 for the proposed rejection gate.
- A retained locked directory is renamed, a replacement parent is created and
  the same inert database inode moved into it. The replacement's raw flock
  succeeds (an expected negative safety observation), but a directory-chain
  anchor persisted in a generic inert SQLite table differs from the current
  chain. This demonstrates the need for immutable parent binding; it is not a
  test of an implemented ProgramTransportStore `/2`.

A second native fork probe recorded **four expected observations**, report
SHA-256 `ce0eb8acb67bea63c3f8d2a96e5b27451eb06a55851098493eb809de80c1157e`.
A minimal registered child callback closes its inherited directory FD without
LOCK_UN; the parent's lock remains busy. After controlled parent os._exit(77),
the child is verified still alive and a new process acquires the directory
lock. The inert child then exits on its explicit local pipe signal. This proves
that narrow native descriptor behavior only, not the full proposed process
registry, fork registration race closure, SQLite quarantine or product replay.
The larger C4 vectors, native product positive and full FC13 remain OPEN.

#### C4 concrete candidate and exact Owner decision boundary

**PROPOSED / OWNER ACCEPTANCE PENDING.** The candidate chooses an existing
parent-directory lock, fresh private store `/2` with one immutable physical
chain field, exact `/1` compatibility, nonblocking shared ownership and bounded
fork lifecycle. Stable trusted local namespace for the entire default-SQLite
connection is an explicit qualification precondition; the proposal does not
pretend SQLite has a descriptor-relative open. No sidecar lock file, public
schema, old-store migration, production override or live authority is added.

The exact six-file SHA-256 manifest is:

- `OWNER_DECISIONS.md`: `727a6e75603e42aa6e663dfdf69305d915a4d267076591f68b66a04252c660fa`
- `docs/v3/boundary-spec.md`: `ba0b86af0915a930a50867d180b8c5de9df248e309403b5a3a66b0023f86c143`
- `docs/v3/acceptance.md`: `67cccb46151ff0e754423b5a61e1cff14c71b00c755a686b75390f32d6c71390`
- `config/context-map.toml`: `fcad7749b6717f14e48022f26e1aca179bbdade9c75941834fa897ca947a60c2`
- `docs/v3/AUTONOMOUS_DEVELOPMENT.md`: `18401fbcb20c8064118e3d785af1b509007bb8a5339ea48a9e18a25bbedb6352`
- `docs/v3/STATUS.md`: `7a3e5f9dbdd08ebc454a21a4392140327d7d564ae86e388d95ad66f39ec3d9c2`

Manifest fingerprint (SHA-256 of the ASCII JSON mapping above, keys sorted,
compact separators `,` and `:`): `172369a9d673f884a2f1b5b9957bbd55eb692af178c0c7373a40fd22ff63033d`.
The dossier is evidence outside that six-file manifest, avoiding self-reference.
The eventual local commit freezes this manifest and the reviewed diff; commit
identity is reported in the clean handoff without altering the frozen files.

Independent read-only C4 review by contract_seam_audit closed its initial
SQLite-path and fork-lifecycle concerns against the proposal's explicit
qualification constraints, effect limits and FD/connection ownership rules.
The private schema/record-version branches, strict/old-store compatibility,
coarse directory lock and exact C2 supersession were reviewed. Final two-file
delta review independently confirmed the corrected Owner heading anchor and
C4-05 driver/epoch effect wording, rehashed the two updated files, and verified
the other four hashes unchanged: no residual P0/P1/P2, proposal PASS. Technical PASS
is proposal-only: the reviewer did not independently execute native probes,
and it is not Owner acceptance or a product/FC13/production PASS.

Owner acceptance of this exact candidate would authorize only the Task
Contract's named offline C4 implementation paths and inert validation, with
independent product review afterward. Current A/B authorization and generic
confirmation cannot preaccept unwritten C4 content. All production, live,
publication, migration and cleanup stops remain. Await the exact-candidate
Owner decision after the clean local freeze; do not implement C4 in this phase.


### C4 Owner acceptance and implementation activation — 2026-09-14

The Owner explicitly replied “接受” to the exact C4 decision request bound to
commit `7409a69b6085d230b1062d3eb1b2c9d17083edbd`, tree
`c5bed0e05887ed2accbec6a261adcf1dde3092d9`, and manifest fingerprint
`172369a9d673f884a2f1b5b9957bbd55eb692af178c0c7373a40fd22ff63033d`.
All six hashes and clean preflight were reverified before product edits.
This activates only the Task Contract's named offline C4 implementation and
inert validation in the current isolated task. The proposal labels above are
retained historical freeze evidence, not a still-pending decision. Production
publisher qualification, live work, publication, integration, cleanup and
scientific acceptance remain unauthorized. Implementation acceptance remains
subject to native evidence and independent review of exact product bytes.


### C4 offline implementation and independent review

Only `auto_g16/transport/program.py`,
`auto_g16/execution/program_runtime.py` and
`tests/v31/transport/test_program_completion.py` changed as product/test files.
The private factory creates `/2` exclusively; v1 default creation and strict
identity/attestation remain independent. The persisted canonical full parent
chain and database nlink/device/inode close the native directory guard. The
process registry, held token, fork quarantine and guarded writer/Execution
checkpoints cover receipt acquisition, persistence, replay and Core reduction.
No product module, public/Core record, production driver or wrapper changed.

For closed version dispatch, the existing SQLite-managed connection reads only
application_id/user_version to identify format, without accepting authority.
Retained pre-open directory evidence and post-open checks precede `/2` guarded
meta/inventory/authority reads; no extra raw DB FD or alternate VFS is used.
The independent implementation seam review rejected adding a directory-lock
restriction to all v1 opens; a native regression proves a v1 store still opens
while a sibling v2 owner holds their shared parent lock. The frozen trusted
stable namespace and disclosed possible local SQLite open/recovery effects
remain essential; this is not a descriptor-bound SQLite claim.

The native test environment is Darwin/macOS **26.6.2**, core Python **3.13.13**,
SQLite **3.53.1**, default sqlite3 configuration. A read-only df/mount check now
identifies the actual temporary volume as **local APFS** on the system Data
volume. This supersedes only the earlier filesystem NOT_ACQUIRED limitation
for this current native run. Other platforms/mounts and other Python minors
are not claimed qualified by these results. Core profile verification passed.

The Darwin-only test-local flock replacement was removed. Existing completion
vectors now use the actual directory lock and default SQLite. Added native
vectors cover independent processes/handles/threads, coarse same-parent
serialization and separate-parent progress, create conflicts/partial files,
closed schema/binding and append-only behavior, hardlinks/copies/lexical aliases,
parent/ancestor replacement, inherited-store rejection, exec restoration,
close/admission race and teardown failure, and owner death with a still-living
fork child. Additional inert Execution vectors preserve evidence while blocking
later receipt, assessment, reconciliation or terminal-state writes after drift.

Independent initial implementation review returned REQUEST CHANGES with two
P1 findings, retained here as history:

1. A fork child could create a fresh store without exec, bypassing inherited-
   instance PID checks. The final global child quarantine rejects every store
   creation/open entrance before file/SQLite effects; only exec starts a new
   process generation. Native tests cover v1/v2 creation, reopen and real exec.
2. Reconciliation could advance UNKNOWN after a just-persisted receipt exposed
   database hardlink drift. Both reconciliation call sites now reattest before
   Core calls; the native inert regression retains the receipt and UNKNOWN.

Author self-review also closed non-owner close/admission atomicity, explicit
store-object binding in the held token, and factory error handling around guard
teardown. No cleanup or retry authority was added. A successful file reservation
that fails initialization remains retained and cannot be silently reused.

The revised independent code review by contract_seam_audit is **PASS**, with
both P1s closed and no residual P0/P1/P2 in the reviewed scope. The reviewer
independently executed six affected native/inert vectors: **6 tests / 1.994
seconds / OK**. That evidence covers the reported repairs and native ownership
cases; it is not a claim of production qualification or all FC01–FC15 acceptance.

Exact final reviewed product/test SHA-256:

- `auto_g16/transport/program.py`:
  `1855fd2b650924ecbf017a1ff612481b08f67a8311c62125b1c5dd2e1b0a3aff`;
- `auto_g16/execution/program_runtime.py`:
  `c669ba71c48de26e4e9d31be45444de1b78a34ef8d9e1ab089c98ae2660ac783`;
- `tests/v31/transport/test_program_completion.py`:
  `7f7c695b80c923ff03a9863ea247530dc096f69044ac4d5a828d0a3a55a405b6`.

Focused development feedback was 50 native completion tests / 92.242 seconds,
9 native store tests / 2.739 seconds, four drift vectors / 6.543 seconds, and
185 adjacent strict/composition/bridge/Lane-A tests / 44.449 seconds, all OK on
their then-current sources. Those pre-final runs do not replace the final
combined frozen-source run recorded below. Three ResourceWarnings in a later
14-test development run came from test-only raw SQLite fixture connections;
they were explicitly closed before the final source hash. No warning was
suppressed in product code and no SQLite locking setting was changed.

Static quality, whitespace/diff, CI declaration and Python contract audits
passed. They attest local declarations only, not remote CI or protection.
The six accepted authority files remain byte-identical to the C4 freeze;
this appended dossier records acceptance and implementation evidence without
rewriting the contract. No full discovery, live operation or deployment ran.


### C4 final bounded checkpoint disposition

Final command on the three exact reviewed hashes, core profile with no test
coverage modifiers:

```text
./scripts/python core -m unittest tests.v31.transport.test_program_completion tests.v31.transport.test_program_composition tests.v31.transport.test_rtwin_successor_bridge tests.v3.execution.test_v31_lane_a -q
```

**253 tests / 153.069 seconds / exit 0 / OK**, no failures, skips or warnings.
UTC start `2026-09-14T11:52:19.052310+00:00`; wrapper completion
`2026-09-14T11:54:52.486128+00:00`. The inventory comprises 68 completion/native
store tests and 185 adjacent strict/composition/bridge/Lane-A tests. It is a
bounded affected run, not whole-repository discovery. Final source hashes were
rechecked after the run and match independent review.

Disposition: **C4 OFFLINE IMPLEMENTATION CHECKPOINT COMPLETE**. The old native
Darwin database-flock/SQLite incompatibility is no longer the implemented C4
lock path: actual native directory ownership, SQLite completion, persisted
capture, reduction and replay have positive evidence. This does not claim
formal complete FC01–FC15/FC13 acceptance, production publisher qualification,
remote CI, branch protection, integration or scientific acceptance. Existing
real receipt-mode publisher hard stops remain active; no user override exists.

Whole-task exact-base selection still includes A's self-protecting manifest/
selector-test edits and must conservatively return legacy-release/fail_closed,
with empty tests and the self-protection reason. No automatic full run follows.
The final local commit, tree and clean preflight/selection evidence are reported
in the handoff, avoiding a recursive evidence-only commit. Isolated branch and
worktree are retained; no publication, deployment, live effect, cleanup or new
user task was performed.

## Offline acceptance closeout after the accepted C4 implementation

The Owner accepted an additional offline closeout in this same task and
worktree: fill missing test evidence, independently review the matrix, freeze
one candidate, and run **one complete full** on that candidate. This supersedes
only the earlier absence of full-run authority. It does not authorize product
changes, deployment, remote execution, publication, PR creation or integration.
The six accepted C4 contract files and both product files remain unchanged.

Closeout starts at commit `b9649ae5a1cbdde5855828db63d3b6bbc43eaaee`, tree
`fec9ad3bc0f317b8f0a089d3096d151516a810a1`. Only this dossier and
`tests/v31/transport/test_program_completion.py` belong to the closeout delta.
Product hashes remain `1855fd2b650924ecbf017a1ff612481b08f67a8311c62125b1c5dd2e1b0a3aff`
(transport) and `c669ba71c48de26e4e9d31be45444de1b78a34ef8d9e1ab089c98ae2660ac783`
(runtime). No old test or fixture method was changed: an AST comparison against
the starting commit found **78 original methods unchanged**, with only the new
`test_closeout_*` methods added. The three adjacent modules in the original
253-test command are byte-identical. This is the basis for reusing E253; no
separate repetition of those 253 was performed during closeout preparation.

### Evidence interpretation and retention

**E253** is the exact prior 253-test run above, with its commit/source hashes,
command, 153.069 seconds and exit 0. It proves only its named assertions.
**N01–N26** below are the additional test method inventory. Their individual
preparation runs and corrections are retained outside the repository in
`validation-runs/v31-file-completion-closeout-20260914T131304Z` under Codex's
local evidence directory. `new-tests-01` through `new-tests-08` contain complete
commands, start/end timestamps, duration, exit status and raw unittest output.
Failed preparation runs are retained; they are not called passing runs.
Final new-only checkpoint: **26 tests / 51.127 seconds / exit 0 / OK**, no
skips, warnings or failures. UTC start `2026-09-14T13:37:03.407175+00:00`,
wrapper end `2026-09-14T13:37:54.915326+00:00`; wall time 51.507808 seconds.
The exact 26-name command and unchanged-source verification are in
`new-tests-final-26.json` and `.log`. Test file SHA-256 is
`97044d09ccf2d65d72c96ec4ec5757228ec9b13859a4d0aeff46f52a790fcbb0`.
This checkpoint excludes all unchanged E253 methods; the subsequently
explicitly authorized complete full will include the entire default inventory.

Corrections addressed test assumptions: thread-local Core connections, the
runtime-attestation API returning an ID, request payload nesting, the existing
manifest grammar allowing additional pinned files, and the inert driver's
constant file token not modeling mtime/ctime after an in-place write.

Independent review prompted three further improvements: explicit reconstruction
of B instead of calling the renderer's helper, recomputed valid Result IDs and
separate fixtures for both corrupted/spliced-byte cases, and a child-local
alarm plus parent pipe/reap cleanup in the native multithreaded fork test.
That alarm bounds only the deliberately adversarial synthetic child. There is
no complete-full timeout, process kill, automatic restart or retry policy.

The complete-full candidate commit/tree, clean preflight, canonical selector,
archive digest and member manifest, interpreter, coverage environment names,
launch PID/run ID and terminal result will be retained in that external directory.
The committed dossier is frozen before complete full; its result is an
external supplement, avoiding a recursive evidence-only commit and second full.
A matrix PASS below means the specified **offline subconditions** have direct
assertions; it is not complete-full success, production qualification, remote
CI, branch protection or scientific acceptance.

### Additional test inventory

All IDs below expand under
`tests.v31.transport.test_program_completion`. `T` means `CompletionTests`;
`N` means `NativeCompletionStoreTests`. The method names are stable references;
line numbers are convenience pointers in the frozen candidate.

| ID | Class and method | Line |
| --- | --- | --- |
| N01 | T.`test_closeout_receipt_nested_closed_grammar_and_limits` | 723 |
| N02 | T.`test_closeout_receipt_inventory_order_scope_and_output_caps` | 775 |
| N03 | T.`test_closeout_operation_output_shape_vectors` | 793 |
| N04 | T.`test_closeout_material_dag_and_nested_manifest_mismatch` | 804 |
| N05 | T.`test_closeout_scheduler_state_and_terminal_priority_table` | 842 |
| N06 | T.`test_closeout_proof_epoch_prefix_bytes_and_order` | 858 |
| N07 | T.`test_closeout_corrupt_and_spliced_durable_bytes_block_replay` | 892 |
| N08 | T.`test_closeout_result_append_failure_keeps_attempt_unfinished` | 914 |
| N09 | T.`test_closeout_result_readback_failure_and_same_id_conflict` | 922 |
| N10 | T.`test_closeout_after_transition_crash_replay_is_idempotent` | 936 |
| N11 | T.`test_closeout_overlapping_collections_have_one_winner` | 953 |
| N12 | T.`test_closeout_wrapper_identity_infrastructure_and_link_faults` | 983 |
| N13 | T.`test_closeout_expanded_review_and_old_version_mode_rejection` | 1068 |
| N14 | T.`test_closeout_fresh_v2_cannot_import_existing_job_authority` | 1100 |
| N15 | T.`test_closeout_assessment_append_failure_reopens_durable_bundle` | 1109 |
| N16 | T.`test_closeout_assessment_readback_failure_prevents_transition` | 1126 |
| N17 | T.`test_closeout_same_result_id_conflict_during_collection_never_advances` | 1139 |
| N18 | T.`test_closeout_manifest_root_inventory_nested_duplicates_and_data_list` | 1150 |
| N19 | T.`test_closeout_capture_drift_and_signal_scheduler_subconditions` | 1175 |
| N20 | T.`test_closeout_same_assessment_id_conflict_never_advances` | 1221 |
| N21 | N.`test_closeout_nested_owner_and_same_descriptor_relock` | 1559 |
| N22 | N.`test_closeout_full_schema_and_independent_v2_identity` | 1575 |
| N23 | N.`test_closeout_schema_meta_and_chain_corruption_fail_closed` | 1607 |
| N24 | N.`test_closeout_root_escape_and_original_path_database_replacement` | 1634 |
| N25 | N.`test_closeout_drift_between_connect_and_authority_closes_connection` | 1646 |
| N26 | N.`test_closeout_fork_rejects_before_other_thread_owned_rlock` | 1662 |

### Required 24-row acceptance matrix

For reused evidence, `T.test_*` and `N.test_*` refer to the classes above;
`P` is `test_program_composition.ProgramCompositionTests`, `B` is
`test_rtwin_successor_bridge.ProductionBridgeTests`, and `L` is
`tests.v3.execution.test_v31_lane_a`. All are within E253. A compound row remains
PARTIAL if any listed required subcondition lacks direct evidence.

| Vector | Status | Covered subconditions and exact evidence | Remaining condition or limit |
| --- | --- | --- | --- |
| FC01 strict compatibility | PARTIAL | xTB v1 replay/v2 construction, CREST v1 replay/v2 tokens: L.ProgramSpecTests.`test_xtb_v1_is_replay_readable_but_not_constructed_initially`, `test_crest_v1_ttconf_is_replay_readable_but_not_constructed_initially`, `test_crest_v2_closed_imtd_gc_fixture_has_exact_semantic_tokens`; old xTB snapshot replay: L.ProgramSnapshotTests.`test_xtb_v1_snapshot_and_approval_replay_keep_historical_scheduler`; default strict T.`test_default_strict_renderer_and_mode_are_unchanged`; all four old-version mode injections N13; V30 surface golden P.`test_30_public_and_v30_surfaces_are_unchanged`; strict terminal/capture B.`test_running_then_exact_exit_zero_owns_success_and_capture`. | NOT_ACQUIRED: independent pre-C2 full spec/snapshot byte-and-ID golden fixtures for every historical version. Current determinism is not that historical comparison. |
| FC02 explicit fresh mode | PASS | N13 checks expanded spec including operation/inputs/outputs, resource/workspace/script semantics and separately closed mode/input/operation/resource/workspace changes against the old confirmation, with zero claim/driver calls. T.`test_fresh_attempt_only_and_bad_material_before_attestation` rejects consumed Attempt conversion. | Offline authority validation only; no confirmation grants production publishing. |
| FC03 binding DAG / C3 material | PASS | N04 explicitly assembles B's closed fields, source hash/size and material hash; extracts exact wrapper/config from deterministic script and checks final artifact/snapshot identity. T.`test_all_receipt_authority_fields_checked_before_returncode` checks every receipt binding; T.`test_changed_receipt_binding_precedes_nonzero`; T.`test_rendered_source_and_material_reclose`, `test_snapshot_review_reopen_uses_only_embedded_material`; N18 covers root inventory, nested duplicates and changed data inventory. Missing/extra material, raw hash/size, wrong profile, noncanonical base64, relocated/duplicate data line, B/material mismatch reject. | Additional pinned runtime files are legal in the historical data grammar; changing the approved list is rejected by its profile identity. No guessed exact-list restriction was introduced. |
| FC04 closed receipt schema | PASS | N01 missing/extra fields at all four nesting sites, nested duplicates, strict integer/bool/float/null boundaries, UTF-8/cap/date/termination/presence; N02 duplicate/partial/extra/reordered inventory, declared output cap, valid multi-input grammar but concrete adapter rejection; T.`test_receipt_grammar_rejects_duplicate_fields_and_bad_types`, `test_all_receipt_authority_fields_checked_before_returncode` includes unknown schema/version. | Synthetic multi-input vectors do not expand adapter input scope. |
| FC05 publisher identity | PASS | N12 malformed marker, executable/input mismatch, input symlink, same-byte new-inode executable/input/marker/runtime replacement; Python replacement modeled at identity return. N04/N18 source/manifest identity. T.`test_wrapper_runtime_dotfiles_and_symlinks`, `test_wrapper_pinned_parent_chain_rejects_replacement`, `test_wrapper_inert_invocation_failure_and_publication_matrix`; production construction/evaluation hard stop T.`test_production_driver_is_unconditionally_blocked`. | Production Linux publisher is BLOCKED/not qualified. All launches/subreaper/wait are inert; Python replacement is a model, other listed replacement files are real temporary objects. Trusted publisher/physical-owner scope does not include arbitrary hostile filesystem writers. |
| FC06 wrapper failure | PARTIAL | N12's 20 scenarios cover wait, log fsync/close/hash, pending byte corruption, existing lock/final/pending/log, pre-link and post-link crashes; original T.`test_wrapper_inert_invocation_failure_and_publication_matrix` covers launch/nonzero/signal/log drift; T.`test_wrapper_waits_adopted_descendants_and_uses_direct_status` covers deadline; T.`test_wrapper_prelink_failure_retains_pending_only`, `test_wrapper_source_compiles_and_no_replace_publication` cover retained pending and no overwrite. N12 asserts zero or exactly one inert launch and retains existing bytes. | NOT_ACQUIRED: real wrapper-process death/OS-managed writer shutdown and same-byte pending-file inode replacement. Source-model exceptions do not prove actual Linux process-death behavior. No automatic retry follows any failure. |
| FC07 direct child status | PASS | T.`test_wrapper_waits_adopted_descendants_and_uses_direct_status` distinguishes direct child and descendant status; T.`test_wrapper_inert_invocation_failure_and_publication_matrix` asserts shell=False and exact environment; fixed wrapper/script contains no tee/pipeline/trap-derived rc authority. N12 infrastructure faults produce no fabricated receipt. | Actual Linux subreaper qualification remains separate and NOT_ACQUIRED. |
| FC08 absence gate | PASS | T.`test_terminal_scheduler_cannot_complete_receipt_mode`, `test_running_receipt_cannot_complete`, `test_absence_without_receipt_is_unknown`, `test_fetch_timeout_is_not_absence_or_nonzero`, `test_final_query_unknown_is_not_absence`; N05 active queued/running/held/exiting, unknown, failed absence and terminal distinctions; B.`test_other_job_duplicate_exit_or_invalid_exit_never_promotes`, `test_raw_scheduler_wire_failure_has_no_invented_raw_audit`, `test_raw_scheduler_eof_and_completion_rejections_are_preserved`. | No time-based R/E recovery and no inference from unreadable/unknown scheduler evidence. |
| FC09 successful receipt | PASS | T.`test_success_durable_bundle_and_zero_read_replay` binds both absence boundaries, Result re-read, assessment and transition; T.`test_single_point_optional_absence_succeeds`; N03 separate operation output closure; N08/N09/N15/N16 prove persistence failures cannot advance. | Execution completion only. |
| FC10 failed program | PASS | T.`test_nonzero_with_absent_required_output_is_failed`, `test_direct_signal_with_absent_output_is_failed`, `test_zero_with_absent_required_output_is_failed`, `test_invalid_geometry_is_execution_failure`, `test_fetch_timeout_is_not_absence_or_nonzero`, `test_fetch_identity_mismatch_is_conflict_before_exit`; N03 unsafe log/geometry values and operation-specific absence; N19 signal agreement. | Untrustworthy acquisition stays UNKNOWN, not manufactured program failure. |
| FC11 scheduler conflicts | PASS | N05 repeated agreeing/disagreeing terminal, missing exit, active after terminal, exact absence; N19 signal=15 vs terminal143/0, terminal after opening absence; T.`test_contradictory_terminal_exit_blocks_nonzero`, `test_final_terminal_contradiction_precedes_awaiting_absence`, `test_later_unknown_blocks_promotion_without_rollback`, `test_later_active_is_conflict_without_rollback`. | Append order owns authority; no fabricated scheduler terminal or exit field. |
| FC12 immutable capture | PASS | T.`test_restat_identity_drift_overrides_exit`, `test_optional_absence_drift_is_conflict`, `test_fetch_identity_mismatch_is_conflict_before_exit`, `test_new_epoch_cannot_replace_accepted_capture`; N19 receipt re-STAT drift, required absence-to-presence and same-size cross-file write with modeled changed physical metadata; N06/N07 exact ID/reference/order and retained-byte provenance. | Constant-token malicious driver is not a qualified physical owner; raw output changes must be reflected in its physical token. |
| FC13 replay/crash | PASS | E253 T.`test_assessment_transition_crash_reopens_without_reads`, `test_bundle_before_assessment_crash_replays`, missing-bundle/history/idempotency tests; N06 exact proof key set, IDs, referenced Result/assessment/capture/receipt, prefix and epoch hash, opening/closing order and inverse finished_at; N07 separate corrupted/spliced fixtures with valid recomputed IDs and byte hashes rejected by persisted provenance, zero-driver replay; N08–N11/N15–N17/N20 append/readback/transition failure, same-ID Result/assessment conflict, both-store reopen and one-winner collection; N21 lifecycle ownership. | Finite offline boundary injections; no live retry, submission, new Attempt, cross-store transaction or scientific acceptance claim. C4 fork-registration-window and historical-store gaps remain separately PARTIAL below. |
| FC14 consumer isolation | PASS | T.`test_strict_consumer_and_historical_collection_reject`; strict consumers reject receipt-mode `/2`; B.`test_seven_operations_use_the_reviewed_rtwin_runner` proves strict authority; static `xtb_crest_handoff.py` calls the same strict helper, which rejects `/2` (static bridge evidence, not a claim that handoff tests ran in E253). | Unsupported consumer/scientific promotion remains closed. |
| FC15 no migration | PARTIAL | T.`test_c4_old_receipt_store_and_strict_v2_reject_before_effects`, `test_strict_consumer_and_historical_collection_reject`, `test_fresh_attempt_only_and_bad_material_before_attestation`; N14 fresh store cannot import existing job authority; earlier UNKNOWN/history cannot be erased (E253 T null-result/history tests). | NOT_ACQUIRED: externally sourced historical `/1` receipt store with actual retained content for raw-read/replay/promotion compatibility. Empty old store and synthetic current authority do not substitute. |
| C4-01 native positive | PASS | E253 T.`test_success_durable_bundle_and_zero_read_replay`, `test_guard_rejects_foreign_token_and_allows_native_sqlite`; N10/N15 reopen both default SQLite stores; no flock replacement or custom VFS on positive path. | Native Darwin/APFS evidence only, not another platform/mount. |
| C4-02 contenders | PASS | E253 N.`test_native_cross_process_and_same_parent_ownership`, `test_native_threads_foreign_tokens_and_close_lifecycle`, `test_separate_parent_progress_and_strict_open_unchanged`; T.`test_guard_blocks_another_store_handle_without_effects`; N11 actual overlapping collections with independent Core connections: loser zero driver/Observation, winner one Result. | Process, thread, handle and same-parent database contention have direct assertions. |
| C4-03 lifecycle | PASS | N08–N11/N15–N17/N20 append, readback, transition, reopen and conflict boundaries; N21 same-FD relock, missing/foreign/nested/stale tokens; E253 N abrupt owner exit/live child, unrelated FD/handle close, T unlock failure and N factory teardown/close race. | Child-local adversarial watchdog is not a full-run timeout. |
| C4-04 fork | PARTIAL | E253 N.`test_fork_child_rejects_inherited_handles_before_locks`, `test_abrupt_owner_exit_with_living_fork_child_releases_lock`, `test_real_exec_restores_fork_child_store_open`; N26 other-thread-owned inherited RLock rejection with self-limited child and parent reap. | NOT_ACQUIRED: actual overlapping fork during FD/SQLite registry insertion window. Mutex coverage is independently source-reviewed, not a dynamic window test. |
| C4-05 physical binding | PASS | E253 N parent/ancestor/symlink/hardlink/copy/alias vectors and same-inode relocation; N23 nonce/schema/store-ID/instance-ID/chain-order/length corruption, N24 explicit root escape and original-path DB replacement, N25 connection-window drift; T C4 mid-driver/Result/assessment/reconcile checkpoints preserve prior evidence and stop later effects. | Pre-body zero driver/epoch effects does not mean zero local SQLite effects. |
| C4-06 schema/create | PARTIAL | E253 N.`test_no_create_retry_or_existing_target_overwrite`, `test_schema_binding_is_closed_and_append_only`; N22 inventory, exact meta columns/triggers, canonical DDL digest, independently rebuilt v2 store/instance/runtime IDs and private `/2` payload; N23 version/application/inventory/DDL/meta/chain drift. | Canonical DDL digest is checked against database definitions, not a separately preserved normative full-DDL golden. Marked PARTIAL rather than calling that assertion independent DDL reconstruction. |
| C4-07 strict/history | PARTIAL | E253 strict `/1` P store/authority inventory and strict-v2 rejection; N13 old ProgramSpec injection rejection; N14 fresh `/2` cannot import previous Attempt/workspace/job authority; N22 `/2` identity reconstruction. | Same historical full bytes/IDs and nonempty `/1` receipt-store evidence gaps as FC01/FC15. |
| C4-08 ordering | PASS | N06/N07 provenance/prefix under replay guard; N08/N09/N15/N16/N17/N20 conflicting append/re-read cannot advance; E253 T drift after Result/assessment and reconcile stops; P.`test_77_product_uses_zero_private_core_schema_access` and source review preserve no-private-Core-SQL boundary. | No atomic transaction across the two stores is asserted. |
| C4-09 trusted namespace | PASS | N25 injects drift after default SQLite open before authority acceptance; connection is closed and artifact retained. E253 full-chain reattestation and mid-body stop tests. Contract retains pathname-SQLite lifetime restriction including journal topology. | No descriptor-bound SQLite or zero-local-effect TOCTOU claim. Production namespace qualification remains required. |

### Environment and final validation boundary

Current local qualification: core Python **3.13.13**, actual native macOS
**26.6.2**, SQLite **3.53.1**, APFS temporary filesystem; chem Python **3.11.15**,
RDKit **2026.03.3**, NumPy **2.4.6**, Pillow **12.3.0**. Core and chem profile
checks and static Python/CI contract audits passed. Required RDKit smoke:
`AUTO_G16_REQUIRE_RDKIT=1 ./scripts/python chem -m unittest tests.test_rdkit_smoke -v`
completed **1 test / 0.061 seconds / exit 0**. No package was installed.

**BLOCKED:** real Draft 2020-12 validation has no existing trusted overlay
matching core Python 3.13 and the exact six locked distributions. Five locked
validator distributions are absent from chem. The reviewed schema entrypoint
was qualified read-only; the real schema inventory was not run and cannot be
replaced by full-suite skips. **NOT_ACQUIRED:** the separately qualified
GoodVibes wheel/entrypoint and Python 3.12 local compatibility evidence. No
network installation or untrusted alternate environment was used.

The whole-task selector must be recomputed from exact base
`6b2ece4443951381f0206c93e55e581ca175dd5e` to the frozen closeout commit. A's
previous manifest/selector-test changes retain the expected `legacy-release`,
`fail_closed=true`, empty tests and exact self-protection reason
`selector, manifest, runner, or selector-test bytes changed`. Manifest blob
`40c01d9b8d00729a2bd8113942caba03348859bc` is unchanged. The runner must independently
validate the serialized selection against both Git identities before launching
the archived candidate's complete inventory, matching the source-archive CI
ownership pattern. This is not fallback discovery after selector error.

The one authorized complete-full command is the qualified core interpreter
running `scripts/run_tests.py --full --top-slow 20 --slow-threshold 1.0` in the
exact Git source archive. It includes all default root-discovered tests with no
pressure/coverage skip modifier. Start and terminal JSON plus complete logs
will be retained externally; this frozen document does **not** predeclare a
PASS, total, duration, CI result or acceptance. Slow/silent progress alone never
authorizes kill, restart or repetition. A failure requires diagnosis and a new
decision, not an automatic second full.

Closeout disposition before that run: additional offline coverage is reviewable;
**complete acceptance is not asserted**. PARTIAL historical/fork/DDL/wrapper
conditions and unavailable separate environment qualifications must remain
visible in the handoff even if complete core discovery exits 0. Final PR-stage
readiness must be assessed against actual terminal evidence and these residual
conditions; no PR, merge, production activation or scientific promotion is
performed by this closeout.


## Authorized historical/environment supplement (2026-09-15)

This related offline test/documentation supplement starts from clean commit
`03ea182a0037630083bdef955eb6e57b8db439c9`, tree
`bfd909c34faffc8879441c233410f6c2918fc7c6`, in the existing isolated task.
The Owner authorized exact locked Schema packages in one new test-only overlay,
baseline Git omissions, historical-source synthetic fixtures and bounded local
inert process probes. Product, Core, public schemas, dependency locks, CI,
runner, selector and scientific authority contracts are unchanged. No new full,
publication, integration, deployment or live/scientific action is authorized.

### Baseline environment omissions

The six wheels were acquired from the explicit trusted PyPI index with exact
versions from `requirements/schema-validation.lock.txt`, then installed offline
into a new private prefix using the existing trusted core Python 3.13.13.
Wheel source, size/SHA-256, install report and commands are retained externally.
No core/chem/global installation occurred; core still has none of these six
distributions. Environment-local Python/pip never runs. The unchanged
`scripts/run_schema_validation.py` retains its descriptor, owner/mode, ABI,
RECORD, before/after package-byte and CI-inventory checks under trusted `-I -S`.

The unchanged CI-owned 28-module inventory passed **144 tests / 899.901
seconds / exit 0 / no skips**: all 123 originally skipped Schema methods plus
21 imported ancillary methods that the canonical inventory also owns. No
filter or runner change was used. Exact IDs are in `schema-inventory-map.json`;
terminal log SHA-256:
`7ec13fc8b7f8118320091dc2639abc43353a4ab7dd40bc6e25abb534fb6c4078`.

The 17 Git-related old skip records expand to **41 actual tests**: 25 methods
behind `LegacyEffectOwnerTests.setUpClass`, one historical stage differential,
and 15 individually selected methods. The exact Git-bearing baseline passed
**41 tests / 175.170 seconds / exit 0 / no skips**. The GoodVibes-named lineage
corruption test is synthetic Git provenance, not installed GoodVibes scientific
qualification. Exact old-to-new selectors/IDs are retained in
`git-inventory.json`; terminal log SHA-256 is
`172258b15109ae1cbc7d2c423ba9500204a6e47b860d168daf06c1840f908b71`.

The earlier unique full remains bound only to `03ea182`: **2736 tests / 2891.839
seconds / OK (skipped=142) / exit 0**. There is a reporting correction: those
142 records consist of 139 skipped methods and three skipped classes; unittest
excludes the latter from testsRun. Hence successful methods were **2597**, not
2594. Original logs remain intact. No full was repeated, and that old full is
not represented as execution on the new supplement commit.

### Independent historical sources and new tests

Six added methods reside in `tests.v31.transport.test_program_completion`.
`T` below denotes `CompletionTests`, `N` denotes `NativeCompletionStoreTests`.
All existing methods/fixtures in that module retain their original AST; the
separate new JSON fixture has a fixed SHA-256 and declared synthetic identity.

| Vector | New disposition | Added direct evidence | Remaining boundary |
| --- | --- | --- | --- |
| FC01 | PASS | T.`test_supplement_historical_source_four_version_golden_bytes_and_ids`: all four xTB/CREST v1/v2 full spec and expanded snapshot bytes, IDs, scheduler content and effect identity reopen exactly; fresh filesystem anchor acquisition is forbidden during replay. Retains prior strict-default/V30 evidence. | These are newly reconstructed historical-source synthetic records, not historical physical/run observations. |
| FC06 | PARTIAL | T.`test_supplement_pending_same_bytes_new_inode_rejected` retains both old/new pending objects and rejects before link. T.`test_supplement_actual_inert_wrapper_process_death` kills/reaps the exact owned wrapper after modeled launch, before link, after link, and after an actual short-lived Python writer was reaped by fixed wait_all. Top-level retained file bytes/dev/inode and publication state remain unchanged after death. | Frozen acceptance explicitly requires surviving descendants. Actual Linux adopted/surviving descendant behavior and publisher qualification remain NOT_ACQUIRED; no-op subreaper and direct-child proof cannot close them. |
| FC15 | PARTIAL | Pre-C4 source reconstructs a nonempty synthetic /1 store externally: 1 meta, 1 runtime and 11 physical rows. Current reader verifies 15 dual-source observations; collection, replay, receipt-proof and strict-proof entries reject with zero driver calls and both database files byte-identical. | No real pre-existing historical nonempty /1 store was found in the bounded task-associated evidence search. Synthetic reconstruction cannot replace that sample or authorize migration. |
| C4-04 | PASS | N.`test_supplement_fork_during_descriptor_registration` and N.`test_supplement_fork_during_sqlite_registration`: real fork overlaps a real open FD/connection before registry insertion; real product mutex delays fork; child closes/quarantines, new child creation rejects and independent contender still loses the parent lock. Retains prior other-thread RLock/exec evidence. | Child watchdog is registered before product import, exact child is reaped, all custom hooks stay in short-lived helper interpreters. Native macOS evidence only. |
| C4-06 | PASS | N.`test_supplement_full_ddl_matches_historical_contract` compares all three table definitions, all six triggers and persisted canonical schema identity to literals derived independently from old Git plus the accepted meta-only column addition. | Historical-source normative reconstruction; not a claim of prior runtime DDL observation. |
| C4-07 | PARTIAL | FC01 supplies exact four-version old bytes/IDs; external old-source nonempty /1 raw-read and fail-closed checks narrow the gap while prior strict and /2 isolation checks remain. | Real historical nonempty /1 sample remains NOT_ACQUIRED as in FC15. |

The required 24 rows therefore become **21 PASS / 3 PARTIAL** after the new
focused validation; all other 18 row dispositions and limits above are retained.
No gap was renamed out of scope to obtain a PASS.

The golden source is pre-C2 commit
`6b2ece4443951381f0206c93e55e581ca175dd5e`, program blob
`c364d7a899c969d2c6e3522f89786d9a5c5fcd88`, fixture blob
`ecfd6612aa7853a0563e51858ae54ba2717c1130`. Fixed synthetic local root and
explicit synthetic descriptor tokens were selected before generation by old
code; no private path was redacted and no identity recomputed afterward.
`tests/fixtures/v31/historical-spec-snapshot-goldens.json` SHA-256:
`d83e1f247223b8c49915859f1cadfa4cebe114dcfc6055e5aebd41ef73ff93ba`.
Current code did not generate the old golden. The generator and source archive
are retained outside Git with source/blob/hash manifests.

The independent DDL uses old transport blob
`3e49198f64e746b7e28a25189abc7a9230ce6cb4` plus accepted C4 boundary at
`7409a69b6085d230b1062d3eb1b2c9d17083edbd`, lines 5686–5692. Its independently
encoded v2 identity SHA-256 is
`725c9fae3fc3027b9b5b81e95e48f96c32931ee4d601b85df552569e00417e80`.
The synthetic nonempty /1 was generated by pre-C4
`502175664ff86185434d8e4a1ba4df4975b52112` using its inert driver and explicitly
modeled Darwin flock. Its exact original path/inode is retained externally;
no database artifact or machine path is committed.

### Validation, review and unresolved responsibility

Final source SHA-256
`1d8a62d0f52f8906d3e2fcb1ab75f39d4a4fa97239f667f0cb2e5cd3a66e07fe`
passed **10 tests / 6.227 seconds / exit 0 / no skips**: six new methods and
four adjacent strict/writer-status/durable-replay/native-contention regressions.
The original 104 class methods are AST-identical. The earlier 10-test draft
pass is retained separately; only an extra EOF blank line was removed before
this final exact-byte run. Final log SHA-256:
`3b7f5c839e6ac93538e312fdca96cebc482c298f38f65dbe0ce5673f289d0e0c`.

The whole-task selector remains subject to its earlier self-protection
`legacy-release` routing. New commit/tree selection is retained externally.
A complete full on the supplement candidate remains NOT_RUN under this
explicit bounded authorization; old full evidence does not fill that new
candidate gap. This is limited offline review readiness, not unconditional
integration or release acceptance.

External evidence directory identifier:
`v31-completion-supplement-20260914T155130Z` under the local validation-runs root.
`history-generation-handoff.json` explicitly points to successful
`history-v1-store-review-02.json/.log` and preserves the prior draft failure;
the latter confused 15 observations with 11 deduplicated physical rows. All
other fixture/probe draft failures are likewise retained and distinguished
from final results. Independent history and fault reviewers cross-review the
other author's evidence; final exact candidate hashes and disposition are
retained with the external closeout report.

The Owner must decide whether to authorize bounded acquisition of a real old
receipt-store sample and Linux surviving-descendant evidence, or accept an
explicit limited disposition while these rows stay PARTIAL. The environment
owner separately owns pinned GoodVibes qualification and Python 3.12 evidence;
no installation of either, new Linux VM/container, or cross-platform inference
was authorized. The supplement prepares reviewable offline evidence for a
possible PR request; it does not grant PR, merge, production or scientific
acceptance authority.
