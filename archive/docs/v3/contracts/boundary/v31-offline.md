# Auto-G16 v3 boundary: v31-offline

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:5149-5190 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V31 private offline closeout boundary

The separately Owner-authorized
[`V31-NIGHT-OFFLINE-CLOSEOUT-20260911`](../tasks/validation.md#v31-night-offline-closeout-20260911)
permits the following private, bounded candidates without changing the
historical shared-contract freeze or current public execution/approval shapes.
These references describe local collection dependencies, not deployed or
merged-main evidence.

- [Scheduler raw evidence](../../scheduler-raw-evidence.md) is a private audit-only
  record in the existing local append-only store. The complete exact QUERY
  request/binding, job identity, locally acquired timestamp, raw stdout/stderr
  bytes, return code/completion fields and digests are retained before the
  unchanged parser normalizes them. Its separate identity domain cannot
  satisfy normalized effect authority. A persistence failure prevents
  normalization; parser failure leaves the raw record available for exact
  replay. The acquisition timestamp is local audit metadata, not a server
  event time, global sequence or scientific ordering proof. This slice begins
  after a transport-frame-closed result; earlier wire acquisition failures are
  outside its capture claim. No public schema, operation or retry is added.
- [Level-2 packet preparation](../../level2-requalification-packet.md) reuses pure
  validators/renderers to propose new Core records, input/spec/PBS/argv
  previews, undecided approvals, effects budget and evidence/reconciliation
  checklist. These are review candidates only. Production snapshot creation
  requires the existing current-attestation owner; the offline tool must not
  call it or fabricate freshness. Missing live prerequisites remain explicit,
  and the tool cannot issue approved records or live/scientific authority.
- [Local program inventory](../../program-qualification-tooling.md) hashes supplied
  local binary and xTB runtime-data files under bounded no-follow reads. It
  neither executes a version probe nor installs or exports files to a server.
  Exact local content identity and an unverified captured version claim do
  not establish production qualification, profile authority or capture
  authenticity. A claimed CREST version must be exactly 3.0.2.

All three preserve no-overwrite, at-most-once submission, `REPLAY` zero effect,
`UNKNOWN` reconciliation-only and no automatic retry. Raw evidence, offline
packets, local hashes and successful tests cannot replace an explicit Owner
decision, a current production physical binding, terminal evidence or
scientific acceptance. No historical incomplete Level-2 acquisition is
retroactively repaired by these candidates.
