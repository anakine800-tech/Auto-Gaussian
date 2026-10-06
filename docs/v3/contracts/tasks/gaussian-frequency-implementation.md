# Auto-G16 native Freq successor implementation

OWNER-GUIDED, non-BUS. OD-37 accepts the byte-preserved r2 proposal
`docs/v3/proposals/gaussian-successor-frequency.md` (SHA-256
`f8bbea9abd11ff064f17c402968777b525b8a497191506450604c61d1479d6be`).
Its historical proposal header is not the current authorization ledger.

Offline implementation, tests and independent read-only review are authorized.
The isolated branch is `codex/native-freq-successor`, based on
`b5f65f6c105a30c416e05dc88e57f7f84e573a08`.
The separately versioned frontend companion begins at
`ebcd03c2850a2cebc0cd4a96c4b5d6e75a473319`, branch
`codex/native-freq-startup`; it does not replace the running installation.

The new closed execution tuple is adapter7/Q8/material9/prebinding10/
scheduler10/deployment8. Historical Gaussian generator modules remain byte
identical. The new tuple consumes the original bounded transport and receipt
owners. The controller inventory includes both new generator dependencies.

Freq Result /2 source and parsed records retain the original store as read-only;
imports append in memory and exclusively publish a new revision. The stage
composition owner replays both native sources and exact retained parsed pairs.
Freq plans bind `optimization_source` (the existing closed five-field Opt
lineage projection) and the stage-independent `method_binding`. These are
ordinary exact plan intent data, not new Core record types or approval records.

`refine_freq_ensemble` replays the original CREST ensemble and every Opt source.
Its `prior` is the retained Opt revision or a fully replayed Freq revision.
For later serial revisions, `history` contains earlier Freq revisions between
the Opt revision and `prior`, in order. Every claimed Freq member must have its
original source replayed; the complete identity payload of each revision is
reconstructed. Missing members, changed evidence and skipped ancestry reject.
Negative and pending members remain in the collection. Thermodynamic and TS
eligibility remain empty.

`auto-g16-freq-readout-registration/1` has the closed fields `schema`,
`material`, `optimization_sources`, `frequency_sources`. Source rows use the
existing pinned source/Snapshot/revision shape. Material has exactly `profile`,
`original`, `opt_refined`, `history`, `prior`, `refined`. Query accepts only the
owning detached reader, selected parsed revision and exact read Snapshot.
Opt and Freq share the existing bounded consumer slot. Unparsed frequency
counts are unavailable; a successfully parsed zero is retained as zero.

Validation is synthetic offline execution plus current-source replay of the
retained Opt candidates. It does not qualify native target loading, transport,
scheduler or process behavior. Before merge, classify and obtain the applicable
explicitly authorized target evidence under the development handbook. Exact
Q8 source commit/tree, installed loader, qualification, actual Freq Attempt,
Snapshot and live window remain separate prerequisites. No real Freq result,
submission, installation, ScientificAcceptance or thermodynamic result is
claimed by this change.

## Accepted tail amendment continuation (2026-10-06)

OD-39 activates the byte-preserved tail r2 proposal (its pending header is historical). Related feature continuation, OWNER-GUIDED/non-BUS, in the same linked worktree and `codex/native-freq-successor` branch; exact starting HEAD `3b9df8c2f287b6a289328711ce2eb52fba2c6dc1`, tree `7116d5d039c9031e5a01fc7f11db21ba8cf0e8bf`. Preflight passed clean before edits. Authorized: contract recording, Conformer tail evidence and version dispatch, fact-only ScientificValidation /2, native readout history dispatch, corresponding offline tests, context map and independent read-only review. Original parser, source/parsed records, transport and installed files remain unchanged. Two repair cycles / 15 active minutes; required running validation/review may finish afterward. No commit/push/PR/merge/install/live authority is added. Evidence is retained outside Git.
