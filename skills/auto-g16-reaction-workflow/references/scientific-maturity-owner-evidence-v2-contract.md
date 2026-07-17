# Auto-G16 Scientific Maturity Owner-Evidence Overlay /2

This prospective overlay closes owner-authority gaps without changing
`gaussian-scientific-maturity-review/1`, `gaussian-scientific-maturity-gate/1`,
or `gaussian-scientific-action-authorization/1`. It emits four separate closed,
hash-bound records:

- `gaussian-scientific-maturity-review/2`;
- `gaussian-scientific-evidence-receipt/1`;
- `gaussian-scientific-maturity-gate/2`; and
- `gaussian-scientific-maturity-action/2`.

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

For every minimum, the receipt replays
`conformer_core.validate_handoff(path)`, its ensemble manifest and selection
review, and requires the selected candidate to be a reviewed cluster medoid
with the exact mechanism state, atom order, composition, charge, and
multiplicity. It also requires the exact base `/1` `conformer_origin` projection,
`scope == minimum_search`, and `source_id == selected_candidate_id`. This removes
an obvious substitution but does not establish candidate-to-input-to-result
lineage: the conformer handoff explicitly ends before exact Gaussian structure,
protocol, resource, and input-hash approval. Because no current owner artifact
closes that chain through the exact minimum result/log, every minimum carries
`minimum_candidate_input_result_lineage_unavailable_v2` and remains not ready.
No TS input or submission action can pass until a later owner contract closes
that lineage.

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
restricted to the exact pilot or formal node set. Current minimum lineage keeps
them blocked. `irc_input` is an intentionally fail-closed interface that returns
`exact_owner_ts_mode_artifact_v2_required`; it does not reuse `/1` booleans.
`formal_barrier_reporting` likewise always returns
`complete_owner_thermochemistry_evidence_v2_required` until a later contract
binds exact edge/node TS, bidirectional IRC, reoptimized endpoints, and complete
thermochemistry/energy owner artifacts. TS input, TS submission, and IRC input
all retain a separate input-review gate; submission also retains a separate
live-approval gate.

The immutable builders are:

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py"
python3 "$TOOL" finalize-review review-v2.draft.json --output review-v2.json
python3 "$TOOL" build-evidence-receipt base-gate-v1.json review-v2.json --output evidence-receipt.json
python3 "$TOOL" build-gate base-gate-v1.json evidence-receipt.json review-v2.json --output gate-v2.json
# Fails closed in the current version until exact minimum input/result lineage exists.
python3 "$TOOL" build-action gate-v2.json --edge-id edge_id --node-id node_id --action ts_input --output action-v2.json
```

The schemas live under `contracts/reaction-workflow/`. Version `/1` consumers
continue to use their historical contracts unchanged; adopting this overlay is
an explicit consumer migration.
