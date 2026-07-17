# Auto-G16 raw QST2/QST3 input audit contract

## Scope

`audit-qst-raw-input` observes one complete user- or GaussView-supplied raw
Gaussian input. It does not generate, normalize, repair, rewrite, stage, or
submit that input. The immutable output schema is
`gaussian-qst-raw-input-syntax-audit/1`; installed-revision evidence uses
`gaussian-installed-g16-qst-syntax-evidence/1`.

The audit supports only `plain_cartesian_qst_multistructure/1`:

- zero or more `%key=value` Link0 lines before one route section;
- exactly one `Opt=QST2` or `Opt=QST3` option;
- two QST2 or three QST3 structure blocks;
- a non-empty title, exactly two charge/multiplicity integers, and one or more
  plain four-column `Element x y z` Cartesian rows in every block;
- ordinary element symbols only, consistent element order, composition,
  charge, multiplicity, and a declared one-to-one atom map; and
- blank-line termination between route, title, coordinates, structures, and
  end of file, with no audited tail section.

Gaussian forms that can be legitimate but are outside this subset are not
called invalid. Atom labels, freeze flags, fragment annotations, dummy atoms,
ONIOM/layer fields, connectivity, Gen/GenECP, pseudo-read, ModRedundant,
external, or other additional tail sections produce
`blocked_unsupported_syntax`. A manual specialist may inspect them, but this
version cannot claim their syntax.

Malformed plain-subset inputs produce `failed`. Placeholder text, a missing or
conflicting QST option, missing titles, malformed charge/multiplicity, missing
blocks or separators, non-numeric/non-finite coordinates, and mismatches with
the supplied atom-map audit are failures. The command preserves the raw file;
it never offers a corrected variant.

## Required hash-bound sources

The CLI requires the exact SHA-256 of the raw input, the pre-existing
`validate-inputs` atom-map audit, and the installed-revision evidence. All
three sources and any optional ZSymb failure record must be existing
non-symlink files below the output artifact directory. The output stores only
portable relative references, byte sizes, and SHA-256 values. It refuses an
existing or symlink output and installs the completed JSON atomically without
overwriting.

QST2 consumes the historical-compatible `validate-inputs` result unchanged.
QST3 additionally requires a `qst3_guess_review` object in that source audit:

```json
{
  "decision": "reviewed_guess",
  "confirmed": true,
  "minimum_claim": false,
  "reviewed_structure_sha256": "<exact ts structure SHA-256>",
  "reviewer": "<non-empty reviewer>",
  "rationale": "<non-empty rationale>"
}
```

The third raw block is recorded only as `reviewed_guess`. It is never an
endpoint, accepted minimum, TS, or path result. Existing `validate-inputs`,
historical family `/1`, and prospective family `/2` artifacts retain their
previous behavior; this command is an additional audit surface only.

## Installed-revision evidence

`verification_status: pending` always produces
`blocked_pending_installed_revision_verification`. A verified record must bind
one exact same-mode known-good raw sample and one hash-bound source. The sample
must replay through the same plain-Cartesian parser. It must also contain a
closed `support_binding` with:

- syntax profile `gaussian-qst-cartesian-multistructure/1`;
- exact assertion
  `exact_qst_multistructure_syntax_supported_for_installed_revision`;
- a source locator that occurs in the hash-bound source;
- `reviewed: true`, reviewer, and rationale.

For `successful_installed_revision_run` and
`gaussview_generated_and_installed_verified`, the source must machine-replay
the declared installed revision, normal Gaussian termination, and absence of
error termination or `End of file in ZSymb`. An official-documentation source
must contain the same QST mode and the exact reviewed source locator. A merely
non-empty manual or GaussView source, a different QST mode, or a null exact
binding remains blocked and cannot produce a runnable-syntax claim.

`syntax_verified_for_installed_revision` means only that the observed raw text
matches this narrow syntax subset and its exact revision evidence. It is not a
scientific input approval, protocol selection, minima gate, calculation-ready
state, submission authorization, or prediction that a job will converge.

## Failure preservation and replay

When `--zsymb-failure-log` and its exact hash are supplied, the file must
contain `End of file in ZSymb`. The result is always
`failed_preserved_zsymb_eof`, even if the current raw text parses. It records
`automatic_rewrite_authorized: false` and
`automatic_resubmission_authorized: false`; trial-and-error separator changes
or automatic retries are forbidden.

`validate-qst-raw-audit` rechecks the canonical payload hash, every portable
file reference, source byte size and SHA-256, the installed-revision evidence
payload and known-good references, the raw parse facts, atom-map/guess binding,
status, and fixed safety fields. Any drift is rejected. Both commands are
standard-library-only and contain no SSH, PBS, Gaussian, deployment, or live
operation.
