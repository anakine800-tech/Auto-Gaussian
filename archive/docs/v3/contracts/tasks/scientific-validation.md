# Auto-G16 v3 tasks: scientific-validation

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:368-409 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V30-MIN-VALIDATE-CONTRACT-01

- **Outcome:** Freeze the smallest post-Result boundary that classifies one
  exact attributed Gaussian job as `VALIDATED_MINIMUM`, `NOT_MINIMUM`,
  `INCOMPLETE`, or `UNSUPPORTED`, plus a separate immutable human
  `ScientificAcceptance` for an exact validated outcome.
- **Scope:** Authority documents and future context routing only. The future
  public owner is `auto_g16.scientific_validation`, with focused tests under
  `tests/v3/scientific_validation/`. It consumes only persisted Result-owned
  `gaussian-job-facts` and binds one exact plan revision, Attempt,
  InputBinding, complete envelope, ParseOutcome, and validation-policy version.
- **Explicit non-goals:** No product/tests/selector implementation; no raw-log
  access, Gaussian grammar, missing-fact reconstruction, Core/Result/Approval/
  Execution/Workflow change, TS/IRC/connectivity, conformer, qRRHO, scientific
  policy framework, Observe, ReviewBundle, Transport, SSH/RTwin/PBS/Gaussian,
  deployment, or live work. `V30-EXEC-02` remained `WAIT` during this completed
  scientific-validation freeze; OD-17 now separately activates only its
  offline composition contract.
- **Dependencies:** Result attribution contract and implementation are closed;
  `GaussianJobParser` / `gaussian-job-facts` is active. Historical failed
  one-section candidates are negative evidence only. Public Result facts and
  their exact source spans are the sole Gaussian evidence authority.
- **Autonomy:** `OWNER-GUIDED`. This lane may inspect current public Result
  facts, draft only the six approved authority files, run lightweight document
  and context checks, and freeze one candidate for independent review.
- **Stop rules:** Stop if any decision needs raw Gaussian bytes, a new Result
  fact/span or semantic change, a Core/API/schema change, upstream contract
  reopening, selector/product/test edits, a nondeterministic heuristic, scope
  expansion, or live authority.
- **Acceptance/validation:** Prove the exact parser tuple and provenance chain;
  equal ordered optimization/stationary evidence pairing; rightmost eligible
  geometry before the final accepted optimization marker; the complete ordered
  frequency-block suffix after its stationary marker; no cross-source splice;
  nonlinear `3*N-6` support; zero negative-frequency tolerance; the exact four
  outcomes; append-only deterministic identities/store replay; acceptance only
  for exact `VALIDATED_MINIMUM`; and all eighteen mandatory adversarial cases
  in `acceptance.md` without raw-output interpretation.
- **Handoff:** Report exact base/head/tree/six-file scope, `PORT`/`DROP`/`DEFER`
  disposition, P0-P3 findings, validation, remaining ambiguity, and the
  independent Contract Review. Completion authorizes neither publication,
  `V30-VAL-SCI-01`, implementation, nor live work.
