# V31 same-Attempt transfer progress boundary

This narrow operational boundary applies when an already submitted V31
Attempt has scheduler absence and an exact output fetch takes long enough that
silence is ambiguous.

- Collection remains bound to the same Attempt, snapshot, effect intent,
  workspace, job authority, file declaration, stat receipt, size, and physical
  file token.
- The only remote operations remain `QUERY_SCHEDULER`, `STAT_EXACT_FILE`, and
  `FETCH_EXACT_FILE`. This change adds no submit, retry, cancellation, cleanup,
  replacement, or new Attempt path.
- During a collection-owned `FETCH_EXACT_FILE`, the local bounded transport may
  emit `auto-g16-v31-transfer-progress/1` diagnostics. They contain only the
  operation, elapsed time, request bytes, received stdout/stderr bytes, and the
  existing byte caps.
- Progress diagnostics are observational. They grant no completion authority
  and are not stored as a program-effect receipt or scientific result.
- Silence or zero received bytes is not failure. The fetch ends only with the
  existing absolute operation deadline, an explicit transport result, or
  complete EOF. An observer failure cannot change that result.
- Partial transport bytes never become a captured output. Completion still
  requires the complete framed response, exact file token and size, verified
  SHA-256, stable restat, final scheduler absence, receipt acceptance, and the
  existing capture/replay checks.
- A timeout, interruption, drift, malformed frame, or missing EOF remains
  `UNKNOWN`; it never authorizes another submission or a replacement Attempt.
