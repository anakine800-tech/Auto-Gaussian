# Auto-G16 V31 CREST native short-entry delivery

Task `V31-CREST-SHORT-PBS-DELIVERY-01` is a bounded v3 successor to
`f199421f725751ebd30d4c9787ebe5fa3c5cff6c`. The Owner explicitly authorized native
startup-payload adaptation, incremental verification, and a fresh real CREST
Attempt on 2026-09-20, retaining the earlier delegated exact-review authority.
The independently accepted 703 diagnostic established short-entry delivery of
the full inert payload. It is not qualification of the production loader or a
scientific run. Historical Attempts, including 697 and 700 UNKNOWN, are immutable.

## SP01 — closed additive tuple

Keep CREST adapter 3, completion receipt `/2`, output grammar, scientific argv,
resource policy and receipt-on-absence semantics. Add only the closed tuple:

- scheduler header `# auto-g16-v31-scheduler/5`;
- rendering material `v31-completion-rendering-material/4`;
- prebinding `v31-completion-prebinding/5`;
- qualification `auto-g16-v31-publisher-qualification/3`, runtime name
  `v31-crest-publisher-qualification-v3.json`;
- deployment `auto-g16-v31-publisher-pilot-deployment/3`;
- payload `auto-g16-v31-crest-startup-payload/1`.

Old xTB and CREST tuples retain their bytes and replay. New material is selected
only by the explicitly present v3 CREST qualification; simultaneous v2/v3 CREST
qualifications reject. Never silently relabel an old qualification.

## SP02 — native immutable declarations

The existing identity-owned `scheduler_artifacts` tuple contains exactly two
ordered artifacts for the new tuple: index 0 is `scheduler-script`, `crest.pbs`,
`pbs-shell-utf8`; index 1 is `startup-payload`, `crest-startup.json`, `json`.
Both use the existing six fields: logical_role, portable_name, format, sha256,
size_bytes, content_utf8. They are deterministic artifacts, not new callable
commands or scientific inputs. One exact scientific seed remains mandatory.

The startup JSON has exactly schema, wrapper_source, config; canonical UTF-8
encoding follows the existing receipt JSON encoder. Config retains the seven
existing closed fields, including material and prebinding. The payload cap is
8 MiB; the short PBS entry cap is 16 KiB, including all metadata and source.
Wrapper UTF-8 is capped at 64 KiB, canonical config at 6 MiB and its base64
delivery at 8 MiB plus the single LF. Duplicate JSON keys and noncanonical bytes
reject. Wrapper digest/length must equal both Q3 implementation and prebinding.
Rendering material is read from the declared payload for this tuple, never from
an arbitrary sidecar or the short entry's third line. Snapshot identity re-renders
and compares both artifacts. Approvals disclose both exact artifacts.

## SP03 — no digest cycle or authority substitution

Prebinding retains its existing predecessor fields. Its material, qualification
and derived wrapper identities are closed before rendering. Payload contains
that prebinding and config; short entry contains the payload digest/length,
fixed payload name, exact workspace, qualified Python identity and approved
Project physical token. Final snapshot/effect identities own both artifacts;
the original native submit-intent marker supplies their final values to the
unchanged receipt flow. No final snapshot digest is inserted into its own payload.

The private renderer receives the verified ProjectPhysicalBinding solely to
bind the startup directory anchor. Public snapshot fields and Core objects do
not gain an extension bag. The final Attempt directory identity cannot be known
before native allocation: launch verifies the frozen Project ancestor token,
opens the exact Attempt component without following links, pins its fresh live
identity, and reattests descriptor/name ancestry before calling the wrapper.
Existing native staging and submit independently bind that allocated workspace.
The anchor comes only from the identity-closed snapshot ProjectPhysicalBinding,
including pure approval replay and assert/re-render; no external token override.

## SP04 — fixed qualified loader, same publisher process

The short entry uses the profile's qualified Python with `-I -S -B -c`, a fixed
source-owned loader and one bounded canonical argument. Its exact closed fields
are schema (`auto-g16-v31-crest-startup-invocation/1`), workspace, project_token,
payload_name, payload_sha256, payload_size_bytes, and server_python (path,
sha256, size_bytes). No environment/path/command override is accepted.

Before executing payload source, validate the canonical argument, expected
interpreter bytes, Project token and every directory component, exact Attempt
containment, UID ownership and 0700 Attempt mode. Read the fixed payload using
no-follow/nonblocking regular-file checks, same-UID ownership, 0600 mode, bounded
stable fstat/read/fstat, exact length/hash and closed canonical JSON. Hold the
directory descriptors and reattest ancestry immediately before execution.

Execute only the captured verified wrapper bytes in memory, in the same Python
process, with a fresh `__main__` namespace, normalized argv and a BytesIO-backed
stdin containing the canonical base64 config plus LF. Do not spawn another shell
or publisher, reopen the payload by name for execution, or add an automatic
retry/fallback. Thus original scientific child ownership, subreaper, wait/reap,
signal/exit mapping and receipt publication continue to belong to the publisher.
The new wrapper/probe are mechanically derived only for the new material,
prebinding and Q literals; reserve crest-startup.json against input/output name
collisions. Existing diagnostic stages remain observations, not authority.
Use fixed `__file__` and builtin mapping in the fresh namespace, not loader
globals. Preserve SystemExit exactly; never convert a wrapper failure to success.

## SP05 — exact native stage and submit closure

Introduce the distinct closed transport artifact kind startup-payload, restricted
to the fixed role/name/format above. Runtime stages seed, short entry and payload
as native exact-byte effects. Common entry still accepts one reviewed seed and
one PBS entry; the payload comes only from the reclosed approved snapshot, never
an unreviewed caller mapping. Local replay reconstructs all declarations and
receipts in the same order.

New submit payloads add exactly `startup_payload_artifact_authority_ids`, an
ordered one-element authority tuple. Old submit payload keys/bytes stay unchanged;
an absent, empty, duplicated or mismatched new authority cannot submit the new
tuple. The bridge accepts only the old closed key set or that exact extended key
set. Native wire closure requires every declared stage once, and the bridge
reattests every staged file immediately before its existing one qsub call.
No protocol operation, retry path, Core state or mutable-source owner is added.

## SP06 — qualification and deployment

Q3 retains all Q2 fields and constraints, with one additional payload field
`delivery_probe` (existing probe shape; case_id P09, outcome PASS), and one new
implementation digest `loader_source`. Wrapper/probe/loader source hashes and
commit/tree bind this candidate; profile basis excludes only the applicable Q3
runtime file to avoid a digest cycle. Contract SHA binds this frozen document.
The evidence index `/3` adds exactly the delivery-probe evidence. Installation
must retain that raw evidence and include the new source file in code pins.

P09 must bind the exact production loader source on the target interpreter and
filesystem, with full payload delivery and pre-entry refusal checks using inert
fixtures. It cannot be satisfied solely by 703's different diagnostic Bash loader.
Reused P01–P08, runtime/ELF closure and host evidence need explicit unchanged-source
and current identity mapping; only missing or invalidated facts are reacquired.
An old host fact is not made current by editing its timestamp. New Q/profile,
native Project/Attempt, deployment and three exact approvals are required.

## SP07 — incremental acceptance and live gate

Cover exact two-artifact rendering/reclosure/approval; missing, extra, duplicate,
truncated or tampered payload; symlink/type/owner/mode/identity and read-race
refusal; native missing-stage/authority and stale replay; one-qsub uncertainty;
same-process wrapper config delivery, ordinary exit/nonzero/signal and receipt
closure; fixed installation/Q3/P09 missing-evidence refusal; old tuple byte parity.
Run focused and affected evidence selected for the frozen candidate; reuse old
passes only for unchanged owned surfaces. Do not rerun unrelated FC06/full tests.
Preserve any mandatory selector/self-protection gate instead of bypassing it.

After independent contract and candidate reviews and exact target qualification,
prepare a fresh native Attempt using the previously accepted xTB seed and frozen
CREST scientific settings. The delegated operator records scientific, finite
batch and operational approval for that concrete snapshot, then submits at most
once. Collect and accept only that same Attempt through native Core/Result replay.
No qdel, spool access, cleanup, overwrite, old-job resubmission or altered chemistry.
Scheduler absence alone is never success. A failed/uncertain real Attempt stops;
it does not authorize another calculation.
