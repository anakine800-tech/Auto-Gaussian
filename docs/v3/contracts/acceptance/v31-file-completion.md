# Auto-G16 v3 acceptance: v31-file-completion

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V31 publisher R4 offline acceptance](v31-successors.md#v31-publisher-r4-offline-acceptance)
- [V31 same-Attempt collection recovery acceptance](v31-successors.md#v31-same-attempt-collection-recovery-acceptance)

<!-- Moved from docs/v3/acceptance.md:2008-2091 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V31-PBS-COMPAT-FILE-COMPLETION-01 candidate acceptance

Candidate under OD-32; not implementation acceptance. This section supersedes
only the old V31 contract-stage prohibition on the explicitly scoped new
candidate and, after Owner L3 freeze, its named offline implementation. Existing
V30 and strict vectors remain binding. Old V31 shared-contract full-run results
are historical, not a requirement to rerun full while authoring this delta.

Contract freeze requires mutually consistent OD-32, boundary, Task Contract,
context routing and status; exact file SHA-256 manifest; independent findings-
first review of those bytes; repository Owner L3 acceptance of the exact
candidate and substantive decisions. Independent technical PASS is not Owner
acceptance. No P0/P1 may remain. A changed candidate invalidates its old review.

The subsequent implementation must demonstrate these offline vectors, with
synthetic data and no real program, network, PBS, cleanup or deployment:

| Vector | Required evidence |
| --- | --- |
| FC01 strict compatibility | Historical xTB v1/v2 and CREST spec/snapshot bytes/IDs, strict default, V30 APIs/receipt/scheduler/capture behavior unchanged; mode rejected on old records. |
| FC02 explicit fresh mode | Version 3 exact mode and expanded review; changed mode/input/operation/resource/workspace makes approval stale; consumed/old Attempt never converts. |
| FC03 binding DAG | Prebinding -> deterministic script -> final snapshot -> pre-qsub marker -> receipt, independent reconstruction; wrong attempt/job/snapshot/effect/spec/program/adapter/wrapper/input/profile/workspace all reject before rc. |
| FC04 schema | Missing/extra/duplicate keys at every nesting; duplicate/reordered/partial/extra input/output members; wrong types, bool/int, float, cap, encoding, timestamps, unknown version and null/presence mismatch reject. Multiple-entry synthetic receipt validator vectors cannot expand adapter input scope. |
| FC05 publisher | Exact marker/source/executable/input identity; nofollow parent/file, symlink, escape, replacement, same-byte new inode, marker drift, untrusted file with correct hash all reject; real production receipt-mode driver construction/evaluation stops publisher-not-qualified before any effect. |
| FC06 wrapper failure | Launch failure, nonzero, signal, wrapper death, surviving descendants, wait error, log close/fsync/hash failure, partial/pending/no receipt, publication conflict/crash before/after the exact link point, existing lock/final file; at most one program launch and no overwrite/delete. |
| FC07 no shell rc confusion | Direct child status differs from collector/tee/pipeline; source cannot use set-e/EXIT trap as rc authority; child rc never fabricated from infrastructure failure. |
| FC08 absence gate | Exact absent is distinct from timeout, SSH/query failure, truncation, parse error, foreign job; Q/R/H/E and mapped aliases never promote; long R/E remains outside recovery. |
| FC09 successful receipt | Both absent boundaries, trustworthy rc=0, immutable capture and separate single-point/optimize output closure; Core advances only after full persisted evidence. |
| FC10 failed program | Trustworthy nonzero/signal with absent required success outputs is FAILED; unsafe/unhashable present output is UNKNOWN; rc=0 missing/invalid required outputs is explicit FAILED diagnostic. |
| FC11 scheduler conflicts | terminal=0/nonzero vs receipt exit and signal mapping; repeated agreeing/disagreeing terminal, terminal before/after absence, active after terminal, unknown after earlier success; no manufactured terminal/exit_status. |
| FC12 capture consistency | Replacement, same-size drift, modification between files, receipt drift, optional/required absence drift, later capture epoch, later conflicting evidence; exact STAT/FETCH ID binding and immutable retained bytes. |
| FC13 replay/crash | Exact replay zero driver calls, assessment/transition crash reopening, durable byte bundle corruption/loss and zero-read reopening, nonblocking physical guard and concurrent collection conflicts, exact epoch/prefix/proof serialization, append order over finished_at, conflicting same-ID payload; no automatic submit/retry/new Attempt. |
| FC14 consumer isolation | `/2` proof never sent as `/1`; unsupported xTB-to-CREST/scientific promotion fails closed; execution success alone never scientific acceptance. |
| FC15 no migration | Historical UNKNOWN/NOT QUALIFIED evidence unchanged; no retroactive completion of jobs with no predeclared wrapper/receipt mode. |

Validation uses syntax/TOML/link/diff and CI-contract audit for contract bytes.
For implementation use focused program identity/composition/bridge and new
completion tests, adjacent strict handoff and V30 transport tests, then exact
base/head affected selection. Record the selector even if it conservatively
routes control-plane changes to full; do not run full without the required
separate integration attestation scope. Selector failure is a blocker, never
permission to fall back to discovery. No full/CI/live PASS is inferred here.

### C3 rendering-material candidate vectors

C3 adds these cases to FC03/FC04/FC05, without claiming they have run:
missing raw material; raw/canonical manifest hash or size mismatch; current
profile drift; duplicate/extra fields; unknown schema/root inventory;
server_python identity/platform/mode mismatch; xTB file-list mismatch;
noncanonical base64; fixed script data line missing/duplicated/relocated or
replaced; B/material hash mismatch; full immutable snapshot reopen with no
mutable profile/cache; unchanged historical strict bytes; synthetic material
never granting production publisher qualification. Independent technical
review and exact Owner acceptance of the C3 content hashes precede dependent
implementation. C2 acceptance remains recorded but cannot fill this missing
input path by inference.


### C4 native controller guard proposed vectors

**PROPOSED / OWNER ACCEPTANCE PENDING.** Supplement FC01/FC05/FC13/FC15 only
if the exact C4 candidate is accepted. The following product vectors are
required evidence after implementation, not claims about the current probes:

| Vector | Required native/default-SQLite evidence |
| --- | --- |
| C4-01 positive owner | On the actual Mac controller, fresh version-2 store and existing public Core store complete an inert receipt epoch, Result re-read, assessment, transition and zero-driver replay while the real directory flock is held; no fcntl monkeypatch, custom VFS or SQLite locking change. |
| C4-02 contenders | Independent processes, threads, distinct handles and distinct databases in the same parent cannot enter concurrently; rejected contenders make zero driver calls/epoch writes. Separate parents can operate independently. |
| C4-03 lifecycle | Exception at each append/re-read/transition boundary, abrupt owner exit, explicit reopen, unrelated FD/handle close, same-FD relock and stale/foreign/nested/cross-thread tokens; release is deterministic and no retry, overwrite or duplicate transition. |
| C4-04 fork | Actual fork while held closes child guard duplicates without unlocking parent, rejects inherited stores before SQLite, fresh process after child exec contends, child remaining alive does not retain dead parent's lock; exec does not inherit it. |
| C4-05 physical binding | Full ancestor and parent symlink/replacement, same-inode database moved into new parent, database replacement/copy/hardlink, alternate spelling, root escape, persisted-chain/nonce/schema/ID drift; pre-body rejection has zero driver calls/epoch writes (not zero local SQLite effects), mid-body drift stops later effects/promotion and retains prior evidence. |
| C4-06 schema and create | Exact `/2` DDL, canonical closed binding and chain order/types, unique create-new reservation, crash/partial initialization, wrong version/inventory/hash; no resume, migration, new lock path or deletion. |
| C4-07 strict/history | Exact historical `/1` IDs/bytes/strict behavior; version-1 receipt history never silently completes via C4; strict rejects `/2`; new-store receipt identity closes existing workspace/Attempt/job authority and cannot import old authority. |
| C4-08 ordering | Every legal version-2 writer and receipt owner participates; replay/promotion rechecks current full prefix under same guard; conflicting Result/assessment or drift after append cannot advance Core, and no private Core SQL/cross-store transaction claim. |
| C4-09 trusted namespace | Default pathname SQLite is not descriptor-bound; qualified connection lifetime excludes uncoordinated topology changes, including journal paths. Injected drift is detected at reattestation, no later effects/promotion occur, and any prior local SQLite effects are reported without claiming zero-local-effect TOCTOU protection. |

Record OS, interpreter, SQLite build and actual temporary filesystem for native
evidence. Each platform/mount claim needs its own observed support; Linux or a
test-local model is not Mac acceptance. Inert OS/SQLite probes justify a design
candidate only; all integrated vectors and full FC13 remain open until proved.
The selector's self-protection after a manifest/test edit remains authoritative;
focused tests and independent review grant no automatic full-suite execution.
