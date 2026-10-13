# Auto-G16 immutable recalculation-decision contract

Status: offline decision-recording slice for `gaussian-recalculation-decision/1`.
This artifact records and validates a human decision about one failed Gaussian
attempt. It does not edit or render an input, expand candidates, retry, stage,
submit, contact SSH/PBS/Gaussian, change chemistry/method/resources, cancel a
job, clean up data, or grant any live authority.

## Authority boundary

Every output fixes:

- `calculation_ready: false`;
- `no_submission_authorization: true`; and
- `no_automatic_retry: true`.

An `approve_one_exact_recalculation_proposal` decision means only that one
human-authored exact delta may enter new, independent protocol, scientific-
maturity, input, and live-approval reviews. All four reviews remain required.
The decision is not an approval at any of those gates and is never executable.

The failed attempt, input evidence, protocol evidence, parsed result, and
terminal evidence remain immutable upstream records. The new artifact is an
evidence-only sidecar. It cannot rewrite a job/result or make a correction by
changing a bound source.

## Portable package boundary

`finalize` and `validate` require an explicit decision package root. Every
draft, evidence, output, and stored artifact path is relative to that root.
Absolute paths, lexical `..`, symlinks, paths escaping the root, URLs, and
machine-local path strings are refused. The artifact stores no package-root or
host path, so the complete package can be moved and validated under a new
root.

The five evidence roles have separate schema allowlists:

| Role | Allowlisted schema families |
| --- | --- |
| `attempt` | RTwin/PBS job records or inspections, sanitized job observations, calculation-attempt links |
| `input` | candidate input handoffs, exact input reviews, Opt/Freq/SP workflows, AllCheck manifests, metal input observations |
| `protocol` | protocol options, selections, or profile sources |
| `result` | generic, Opt/Freq/SP, TS/Freq, asymmetric TS, or metal result observations |
| `terminal_evidence` | terminal intake or job inspection |

Schema-bearing evidence must be JSON and match its role. A result schema cannot
be supplied as a protocol. Unknown evidence may be retained only with
`schema: null` and an allowlisted media type. It remains `evidence_only` and
gets no owner or scientific authority.

Each binding records `sha256`, byte size, media type, optional declared payload
hash, and:

```json
{
  "integrity_validation": "bytes_only",
  "owner_validation": "not_performed_no_semantic_acceptance"
}
```

For explicitly registered payload fields, the CLI recomputes the declared
payload hash. That is integrity replay only. It is not an owner validator and
does not prove that the source satisfies its complete schema, specialist
semantics, acceptance rules, or scientific gate. A future source may claim
owner validation only after this CLI registers and invokes that exact owner
validator; V1 registers none.

## Human review and exact preserved facts

The ephemeral draft uses `gaussian-recalculation-decision-draft/1` and must
provide:

- a reviewer, timezone-bearing review timestamp, notes, and uncertainties;
- a human failure category, summary, and at least two exact evidence selectors
  spanning at least two bound roles;
- JSON Pointers to the original method, route, resources, and every retained
  structure hash; and
- zero or more human-authored candidate actions consistent with the decision.

Finalization dereferences those JSON Pointers. It copies exact string values,
canonicalizes structured values, computes value hashes, and binds the exact
input/protocol file hashes. Validation repeats the dereference and refuses
source drift or a rehashed derived edit.

`normal_termination_count`, a `Normal termination` marker, or one error code is
never sufficient to create a failure classification or a decision. The
artifact fixes `normal_termination_alone_sufficient: false`,
`single_error_code_alone_sufficient: false`, and
`automatic_inference_performed: false`.

## Decision and proposal rules

The decision enumeration is closed:

- `no_retry`: no candidate action;
- `defer`: one or more proposals, all marked `deferred`;
- `approve_one_exact_recalculation_proposal`: exactly one proposal, marked
  `selected_for_separate_gate`; or
- `reject_proposal`: one or more proposals, all marked `rejected`.

Every proposal contains one or more exact `from`/`to` canonical JSON deltas.
The `from` value must replay from a bound JSON Pointer; the `to` value must be
canonical, different, and explicitly `human_authored`. It also requires
scientific and numerical rationale, impact scope, risks, and all four new
review gates. The CLI does not generate, rank, broaden, or modify proposals.

## CLI

Place the draft and all five evidence sources below one package root:

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/recalculation_decision.py"

python3 "$TOOL" finalize --root decision-package \
  review.draft.json \
  --attempt evidence/attempt.json \
  --input evidence/input.json \
  --protocol evidence/protocol.json \
  --result evidence/result.json \
  --terminal-evidence evidence/terminal-intake.json \
  --output recalculation-decision.json

python3 "$TOOL" validate --root decision-package \
  recalculation-decision.json
```

All paths other than `--root` are package-root relative. Finalization refuses
overwrite. It writes and `fsync`s an exclusive same-directory temporary file,
then uses an atomic no-clobber hard-link publication. If the target already
exists or an external writer creates it concurrently, publication fails and
the other target is never overwritten. Failure removes the temporary file so
a partial file cannot be mistaken for an artifact.

## Residual limitations

- V1 records one decision for one exact five-role evidence set; it is not a
  multi-attempt comparison or retry scheduler.
- V1 registers no owner validators. All source bindings explicitly remain
  integrity-only and non-authoritative.
- Raw non-JSON evidence can be retained, but JSON Pointer assertions cannot be
  made against it.
- The artifact does not decide whether a proposed method, structure, route, or
  resource change is scientifically appropriate. That remains the work of the
  independent future gates.
