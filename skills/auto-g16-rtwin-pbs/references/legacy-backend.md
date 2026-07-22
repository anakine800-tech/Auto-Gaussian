# Auto-G16 v2.6 legacy backend boundary

`gaussian_rtwin_pbs.py` is the retained CLI/import wrapper. The only execution
implementation owner is `legacy_rtwin_pbs.py`, reached through
`execution_facade.py`. The facade has no module parameter or module-cache
selector and always imports `legacy_rtwin_pbs`. `gaussian_auto.py` binds that
facade; no CLI or environment value can choose another engine.

PR4A preserves the fixed `/home/user100/SDL` root, PR2-owner-sealed exact legacy
resource tuples, fixed PBS rendering, unknown/uncertain classifications,
immutable fetch, one-shot mutation and no-delete rules. The PR3 strict
no-follow loader seals active attestation operations into non-executable plans.
Scientific method/input/result owners are unchanged.

New non-dry-run submission rejects historical live approvals and requires
`auto-g16-execution-authorization/1`, then stops at
`transport_integration_required` before persistent consumption or external
mutation. PR4B must add production transport integration from the exact PR4A
commit. Complete PR4 then requires independent L3 review and a separately
authorized exact live smoke; PR4A must not merge independently.
