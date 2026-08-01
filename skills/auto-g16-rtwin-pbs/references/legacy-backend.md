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

The v2.6.1 B1 non-dry-run production command uses the existing exact-input,
resource-bound one-time live approval and execution-batch transaction gates.
After those gates pass, the fixed legacy adapter invokes the pre-existing sole
transaction/effect chain. There is no backend selector, second qsub path,
automatic retry, qdel, overwrite, cleanup or server-data deletion path. Live
behavior remains unverified until a separately authorized exact live smoke.
