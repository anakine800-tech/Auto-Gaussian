# Auto-G16 Scientific Maturity Owner-Evidence Overlay /2

This prospective overlay closes owner-authority gaps without changing
`gaussian-scientific-maturity-review/1`, `gaussian-scientific-maturity-gate/1`,
or `gaussian-scientific-action-authorization/1`. It emits four separate closed,
hash-bound records:

- `gaussian-scientific-maturity-review/2`;
- `gaussian-scientific-evidence-receipt/1`;
- `gaussian-scientific-maturity-gate/2`; and
- `gaussian-scientific-maturity-action/2`.

For an exact formal-TS submission scope, the owner may also emit
`gaussian-scientific-action-authorization/2`. It binds one passed
`ts_submission` action `/2`, exact Gaussian input bytes, project, work kind,
resource tier and reviewed task/core-hour/concurrency budget. It remains
offline evidence with `calculation_ready: false` and
`no_submission_authorization: true`; it is never a live approval.

Every record is offline evidence only. `calculation_ready` is always `false`,
`no_submission_authorization` is always `true`, and no record selects a method,
renders an input, approves an input, stages work, or authorizes a live action.

## Exact ancestry and owner replay

The review binds one exact validated maturity gate `/1`. The receipt then calls
the public validators for its calculation plan, reaction mechanism support,
TS-precedent map, each conformer candidate handoff, every applicable main-group
open-shell result acceptance, and each referenced manual-evidence receipt. New
`/2` bindings are relative to their owning artifact, reject `..`, absolute
paths, and every symlink in the path chain, and are checked for file, size,
schema, and payload hashes. Outputs use immutable exclusive creation and never
overwrite.

This does not retrofit portability into owner artifacts. Current conformer
artifacts may contain absolute bindings, and current open-shell source paths may
be relative to the process working directory. The overlay replays those owner
semantics exactly and fails closed after a package move or working-directory
change; portable relocation of the complete owner chain is unsupported in this
version. Containment checks must not be relaxed to make a moved chain pass.

For each edge/channel, the receipt requires the exact plan/network ancestry,
the selected support records, their projected exploration and mechanism-claim
states, an exact promoted precedent record or bounded de-novo plan, and no
remaining plan blocker. A de-novo seed remains pilot-only. A matching artifact's
mere existence never promotes an edge.
The sole `endpoint_anchored_ts_candidate` action remains pilot science: it can
bind exactly two accepted 84-atom neutral-singlet minimum lineages to one
general-tier QST3 candidate search, but must keep mechanism and accepted-TS
claims false, limit task/concurrency to one, and forbid automatic retry.

For a conformer-search minimum, the receipt replays
`conformer_core.validate_handoff(path)`, its ensemble manifest and selection
review, and requires the selected candidate to be a reviewed cluster medoid
with the exact mechanism state, atom order, composition, charge, and
multiplicity. It also requires the exact base `/1` origin projection,
`scope == minimum_search`, and `source_id == selected_candidate_id`.

An already calculated and explicitly reviewed Opt/Freq minimum may instead use
a null conformer handoff and a `gaussian-minimum-lineage-handoff/2` whose
`source_kind` is `reviewed_result`. Its base origin scope must be
`accepted_minimum_result_review`, and its source ID must equal the exact lineage
review ID. The lineage review itself is replayed as the origin and must bind the
same minimum, mechanism state, stable atom order, identity, connectivity and
stereochemistry. This route never fabricates a conformer ensemble or medoid.

For either origin, the supplied minimum lineage is replayed by its public owner
and must bind the exact input, project/job/attempt, terminal inspection receipt,
fetch snapshot, raw log, result, checkpoint and optimized coordinates. Missing
lineage or any cross-source/attempt substitution retains
`minimum_candidate_input_result_lineage_unavailable_v2`; only the exact
owner-replayed chain sets `owner_evidence_ready`. This remains scientific
evidence and grants neither input nor live authority.
When an exact reviewed-result lineage `/2` passes that replay, it is the
successor owner for historical minima that predate the combined Opt/Freq/SP
result schema consumed by gate `/1`. Only the inherited
`start_minimum_not_accepted` and `end_minimum_not_accepted` compatibility
blockers are displaced. Every other literature, mechanism, precedent, mapping,
mode, path, budget, input and live blocker remains in force. Atom correspondence
is checked by stable atom ID and element; canonical JSON atom sorting is never
treated as Cartesian coordinate order.

If the immutable historical terminal receipt has no PBS session and therefore
records process evidence as unknown, the lineage may additionally bind one
`gaussian-terminal-process-reconciliation/1`. Its two raw project/stem probes
must be hash-bound, at least five seconds apart, and each show zero matching and
zero unresolved relevant processes. Only `sshd` and `sftp-server` records with
readable command lines may be excluded as known infrastructure. The successor
does not modify the historical receipt or fetch snapshot, and any process
match, unreadable relevant process, target drift, raw-byte drift or receipt
cross-binding fails closed.

Supported main-group doublets and high-spin triplets additionally require an
exact accepted `auto-g16-main-group-open-shell-result-acceptance/1`. The overlay
calls `open_shell_state.validate_artifact(path)` and binds its validated review
candidate to the selected conformer, element order, charge, and multiplicity.
It projects the specialist candidate-source, structure, observation, and raw-log
hashes as validated facts. The current specialist observation has no input hash,
candidate geometry, or structure-hash comparison, so acceptance does not close
the minimum lineage blocker and cannot promote a substituted same-state log.
Closed-shell minima must not supply this evidence; metals and electronic states
outside the specialist V1 scope remain blocked.

Manual receipts are supporting evidence only. Syntax/version context requires a
`gaussian_program_manual` receipt whose claim scope is
`gaussian_syntax_or_version`; general theory and non-version Gaussian text may
not support installed-version syntax. Electronic-structure context accepts only
the corresponding Gaussian non-version or general-theory claim scopes. The
receipt replays and projects adapter/store/database/row/text hashes, source
kind/scope/program/version/object/payload, locator/text quality, downstream
role, applicability, installed-version review, and uncertainties. In
particular, `applicable_with_limits` retains its non-empty uncertainties.
Manual evidence never replaces
literature, mechanism, precedent, minimum, protocol, input, or live approval.

## Consumer API

Later TS and RTwin/PBS families may import the module and call:

```python
validate_evidence_receipt(path)
validate_gate(path)
assert_action(gate_path, edge_id, node_id, action, pilot=False)
validate_action(path)
```

`action` is one of `ts_input`, `ts_submission`, `irc_input`, or
`formal_barrier_reporting`. TS input and submission retain the exact plan
`node_kind` (`ts_candidate` or `ts_freq`) instead of a synthetic label, and are
restricted to the exact pilot or formal node set. Missing or invalid minimum
lineage keeps them blocked; an exact owner-replayed lineage `/2` can close each
endpoint without removing unrelated blockers.
`irc_input` is an intentionally fail-closed interface that returns
`exact_owner_ts_mode_artifact_v2_required`; it does not reuse `/1` booleans.
`formal_barrier_reporting` likewise always returns
`complete_owner_thermochemistry_evidence_v2_required` until a later contract
binds exact edge/node TS, bidirectional IRC, reoptimized endpoints, and complete
thermochemistry/energy owner artifacts. TS input, TS submission, and IRC input
all retain a separate input-review gate; submission also retains a separate
live-approval gate.
`resolve_ts_endpoint_minimum_lineages()` may expose accepted endpoints for both
formal and endpoint-anchored candidate actions; the projection remains
non-authorizing. Only action authorization `/2` may recognize the exact
84-atom general-tier exception.

The immutable builders are:

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py"
python3 "$TOOL" finalize-review review-v2.draft.json --output review-v2.json
python3 "$TOOL" build-evidence-receipt base-gate-v1.json review-v2.json --output evidence-receipt.json
python3 "$TOOL" build-gate base-gate-v1.json evidence-receipt.json review-v2.json --output gate-v2.json
# Passes only when exact owner-replayed minimum input/result lineages and all
# remaining pilot evidence are present.
python3 "$TOOL" build-action gate-v2.json --edge-id edge_id --node-id node_id --action ts_input --output action-v2.json
```

The schemas live under `contracts/reaction-workflow/`. Version `/1` consumers
continue to use their historical contracts unchanged; adopting this overlay is
an explicit consumer migration.
