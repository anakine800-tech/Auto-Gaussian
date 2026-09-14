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
