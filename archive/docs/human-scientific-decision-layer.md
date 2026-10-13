# Auto-G16 Human Scientific-Decision Layer

This offline slice records three immutable artifacts. It does not create a
Gaussian input, mark a calculation ready, authorize submission, or perform a
live action.

1. `gaussian-mechanism-discussion/1` binds the exact mechanism proposal,
   mechanism network, and evidence bytes. It records the question, facts,
   uncertainties, alternatives, AI recommendation and risk, plus the exact
   explicit user decision and approver/time. AI content is always
   `proposal_only`; neither the assistant nor an automated command can create
   user confirmation.
2. `gaussian-operator-action-card/1` states `run`, `defer`, or `reject`, exact
   scope, prerequisites, scientific value, estimated cost or `unknown`,
   calibrated success/closure confidence or `unknown`, stop conditions,
   continuation, rollback, and the closed unauthorized-action list. A `run`
   card still remains a recommendation and requires a current confirmed
   discussion.
3. `gaussian-study-learning-update/1` binds new evidence and records
   observations separately from proposal-only interpretations. It cannot
   rewrite an approved decision. Changed evidence affecting an approval must
   use `invalidates_requires_new_discussion` and obtain renewed confirmation.

Use one portable package root and package-relative, non-symlink paths:

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/human_scientific_decision.py"

python3 "$TOOL" build-discussion --root package discussion.draft.json \
  --mechanism mechanism.json --network network.json --evidence evidence.json \
  --output mechanism-discussion.json

python3 "$TOOL" build-action-card --root package action-card.draft.json \
  --discussion mechanism-discussion.json --output operator-action-card.json

python3 "$TOOL" build-learning-update --root package learning.draft.json \
  --discussion mechanism-discussion.json --evidence new-evidence.json \
  --output study-learning-update.json

python3 "$TOOL" validate --root package mechanism-discussion.json
```

The builder refuses stale source hashes and output overwrite. Validation
replays every bound file hash and payload hash, so editing evidence after a
decision invalidates downstream validation. This slice intentionally does not
alter the existing reaction-workflow `/1` artifacts; promotion/handoff owners
must explicitly consume these new contracts in a later integration slice.
