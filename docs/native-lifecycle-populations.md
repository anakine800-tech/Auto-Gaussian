# Native lifecycle and saved dual populations — candidate contract

Authorization recorded 2026-10-12: isolated frontend worktree based on reviewed
fc074e5708999ad60c18510ef49328efdfbca194; branch codex/native-lifecycle-populations.
Allowed: precise contract freeze, independent review, implementation, offline and
isolated local synthetic browser acceptance. Backend worktree is read-only input.
No calculation, collection, SSH/PBS/qdel, scientific parameter changes, evidence
overwrite, 8772 installation/switch, commit/push/PR/merge, or other-worktree edits.
Jobs 745–750 remain untouched. Frontend acceptance is not scientific E2E.

Preflight: clean approved HEAD verified, dedicated worktree and branch, no applicable
AGENTS.md in this frontend checkout or ancestors, README/CI/registration rules read.
No frontend preflight command exists. Existing offline test entry points retained;
backend preflight is not executed against or modified in another worktree.

Freeze: GET /api/v1/native/sources/{source_id}/attempts/{attempt_id}/lifecycle
and /populations use the existing authentication/origin/method/query/body/size/error
boundary. Forward only to NativeQueryService.get_lifecycle / get_populations.
If an owner method is absent, confirm membership using existing get_attempt then
return the corresponding versioned envelope with unavailable/backend-unavailable,
null result (and null selected_member_id for populations). This frontend-only
fallback reason is additive; owner not-registered and lifecycle-job-not-established
remain distinct. No HTTP configuration, paths, kernel, builder, saving or remote calls.

Closed browser contracts: exact lifecycle schema auto-g16-native-lifecycle-query/1,
kind lifecycle, data source_id/attempt_id/availability/reason/result; result follows
backend docs/v3/contracts/tasks/butane-reliability-e2e.md lifecycle /1 exactly.
Historical observed_at and raw_state must be null. Axis state/reason/availability
combinations are checked, evidence references are unique and retained verbatim.
The projection is historical, no polling, no current timestamp or inferred raw R.

Population schema auto-g16-native-populations-query/1, kind populations follows
populations-appendix-draft.md approved 2026-10-12: exact public whitelist at every
nested level, exactly two distinct members and unique Opt/Freq associations,
selected Freq matches route, reference is in the pair, finite saved numbers,
positive integer g/sigma, range-checked populations, stored normalization metadata.
No subtraction, energy conversion, logarithm, exponential or normalization in UI.
Only saved fraction-to-percent presentation is allowed. Preserve saved numbers,
reference ID, Gaussian sigma, g/rationales, all public identities and hashes.
Existing thermodynamics panel remains the source of saved low-frequency parameters.
New panels request once after detail; use 120-second scientific-read deadline and
existing page-wide two-slot budget, discard stale routes/tokens, no automatic retry.
Old DTOs and registration versions remain unchanged in this initial slice.

Validation: interleaved lifecycle axes, unavailable/errors, missing/extra/nested
fields, unknown schemas, source/Attempt/member/reference mismatch, navigation and
token isolation, old DTO compatibility, HTTP read-only boundaries and zero compute.
Synthetic screenshots must be labelled synthetic. Real registered backend/HTTP/UI
joint validation and unified installed entry remain explicit pending dependencies.

Independent contract review: no blocking findings. Pair hash association and
unavailable low-frequency parameter messaging added. Reviewed input snapshots:
- Backend `docs/v3/contracts/tasks/butane-reliability-e2e.md` SHA256
  `9361b719576d95c1110b3c12e68956d67dd4868b07457f268205de5cd9c4dbe0`
  (parent appended population contract during this task; lifecycle /1 unchanged).
- Approved `populations-appendix-draft.md` SHA256
  `d9c57bc17857ed089bae755f62c86adb5d99233818875e57ef8b7de972996495`.
Private absolute input locations are retained in the local evidence packet only.

## Trusted startup registration /5 — additive follow-up freeze

The authorized parent feedback on 2026-10-12 permits this narrow startup extension.
`autog-native-source-registration/5` retains the exact top-level `{schema,sources}`
and adds one required `population_readout` field to the exact /4 source fields.
The field is null or exactly `{path,sha256}`, with string values, an absolute path
and lowercase SHA256 accepted by the existing pinned reader. Null passes no new
backend keyword, allowing an older backend to retain the /4 null behavior. A
non-null descriptor requires non-null `thermodynamic_readout` and `freq_readout`;
otherwise reject before loading population registration. Missing backend loader
fails startup closed; never silently discard a requested registration.

Read the descriptor with existing bounded no-follow `read_pinned`, cap 1 MiB, then
call only `load_native_population_readout(content,digest)`. The backend owns the
closed `auto-g16-native-populations-readout-registration/1` envelope, both physical
bindings, type and exact equality with the already registered thermodynamic
artifact/frequency sources. Pass its exact reader as `NativeSource.population_readout`;
never reconstruct bindings or call `.read()`, builder, saver, parser or kernel at
startup. NativeSource and NativeQueryService retain final owning validation.
No database is opened merely to load frontend registration. Registry, source count,
snapshot and old descriptor limits remain unchanged; /1–/4 retain exact old keys.
No new CLI flags, HTTP paths/registration fields, deployment or service switch.

Acceptance: old versions byte/field compatibility; /5 null without new backend
capability; missing/extra/duplicate fields; malformed/hash/oversize/symlink
population descriptors; exact byte/digest/limit/reader forwarding; missing paired
thermo/Freq rejection; owning registration mismatch rejection; no startup result
read, database write or compute. Descriptor wiring unit tests are not real data
joint acceptance. Genuine saved-artifact registry→Query→HTTP validation will use
an exact accepted backend candidate and remains explicitly pending until supplied.

The /5 contract and implementation passed independent read-only review. The local
30-test startup/HTTP/UI-boundary run passed, including eight new descriptor wiring
and rejection tests. Owning loader/NativeSource errors are tested for propagation;
valid actual saved population binding and registry→Query→HTTP acceptance remain
pending, not established by these mock-isolated descriptor tests.
