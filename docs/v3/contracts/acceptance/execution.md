# Auto-G16 v3 acceptance: execution

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:141-179 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-EXEC-01: Frozen Offline Execution Boundary

**Status: SATISFIED / INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The numbered conditions
below remain the acceptance contract; integration grants no SSH, RTwin, PBS,
Gaussian, deployment, or other live-effect authority:

1. Semantically identical snapshots keep one identity across JSON key order or
   formatting changes.
2. Any effect-relevant field change produces a new snapshot identity.
3. Mutable ServerProfile changes stale an unexecuted snapshot and require fresh
   resolution.
4. Windows relative, home-relative, and `~` paths are rejected.
5. POSIX relative or non-canonical paths are rejected.
6. PBS template identity derives from exact bytes; an opaque caller ID is
   rejected.
7. `PreparedInputBinding` binds exact prepared bytes durably to the
   CalculationPlan, revision, and Attempt.
8. `ResolvedResourceRequest` binds the exact ResourceSpec and effect-time
   values while remaining separate from scientific intent.
9. An existing Project can receive a fresh Attempt workspace.
10. Local, RTwin, and server workspaces are Attempt-specific, contained,
    no-follow where effectful, and no-overwrite.
11. Partial workspace allocation persists explicitly and never masquerades as
    globally no effect.
12. Concurrent claims yield exactly one Core `WINNER` for a submission intent
    and at most one submission call for the Attempt.
13. `REPLAY` makes zero adapter or external-effect calls.
14. Pre-effect failure records no-effect evidence and is not `UNKNOWN`.
15. Possibly effectful submission ambiguity becomes `UNKNOWN`.
16. `UNKNOWN` permits same-Attempt reconciliation, never automatic retry.
17. Minimal `RemoteEffectReceipt` replay is idempotent and conflicting content
    is rejected; all three frozen effect states and `effect_sequence` are
    covered.
18. The RTwin synthetic adapter needs no real SSH, PBS, or Gaussian.
19. Core remains transport-free.
20. No `qdel`, cancellation, deletion, cleanup, deployment, or live behavior is
    exercised or authorized.
