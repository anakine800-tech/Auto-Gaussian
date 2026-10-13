# Auto-G16 v2.6 offline platform contracts

`scripts/platform_contracts.py` is the single Python owner for the v2.6 PR2
contracts. It is offline-only and does not implement SSH, RTwin, PBS, Gaussian,
a handshake, a remote command, an execution backend, or an authorization gate.
It does not modify the legacy runtime file.

The new closed schemas are packaged from `contracts/execution/` without a
second repository copy inside the Skill. The packaged legacy mapping also uses
the exact root `scripts/runtime_config.py` owner bytes. Historical schemas and
their validators remain unchanged.

## Offline doctor

Inspect a legacy runtime with the original `/1` loader and emit only a
sanitized deterministic mapping summary:

```bash
python scripts/platform_contracts.py doctor \
  --legacy-runtime /absolute/private/auto-g16/runtime.json
```

For nested legacy transport, the result remains
`live_attestation_required`. It does not read the second-hop config, connect,
or create a receipt. Supplying both a profile and legacy runtime performs a
field-name-only conflict diagnosis; it never silently migrates or falls back:

```bash
python scripts/platform_contracts.py doctor \
  --profile /absolute/private/auto-g16/execution-profile.json \
  --legacy-runtime /absolute/private/auto-g16/runtime.json
```

Capability output means configured expressibility only. Reachability, license
validity, Gaussian availability, identity attestation, and live authority stay
unknown. Local Gaussian, Slurm, and MCP stay explicitly unsupported.

## Explicit profile init

`init` requires an already validated hash-only TransportIdentityBinding. It
does not resolve or parse SSH configuration. `--dry-run` writes nothing and
prints only a sanitized summary:

```bash
python scripts/platform_contracts.py init \
  --output /absolute/private/auto-g16/execution-profile.json \
  --profile-id placeholder-profile \
  --backend-kind legacy_rtwin_pbs \
  --transport-config-ref /absolute/private/auto-g16/placeholder-ssh-config \
  --identity-binding /absolute/private/auto-g16/identity-binding.json \
  --dry-run
```

Omit `--dry-run` only as an explicit local write request. The destination is
reported exactly, ancestors and the leaf must be no-follow, an existing file
is never replaced, publication uses a validated same-directory temporary inode
and an atomic no-clobber hard link, and the final mode is `0600`.

All backends remain fixed to `/home/user100/SDL`. The legacy resource catalog
is exactly simple 8 cores/12 GB, general 22/50, and complex 44/120. A
`custom_reviewed` tuple is only structurally expressible within 44/120 and is
still non-authorizing; walltime always remains explicit. PR2 does not create a
resource approval or consume the existing gate.

## Offline validation

The `validate` command accepts profiles, bindings, catalogs, capability
reports, legacy mapping results, and typed first/nested-hop requests and
receipts. Receipt validation requires the exact request/binding inputs; nested
receipt validation also requires the exact first-hop request and receipt.
Pass `--now` to bind validation to an explicit RFC3339 UTC instant.

```bash
python scripts/platform_contracts.py validate first-hop-receipt \
  /absolute/private/auto-g16/first-hop-receipt.json \
  --request /absolute/private/auto-g16/first-hop-request.json \
  --identity-binding /absolute/private/auto-g16/identity-binding.json \
  --now 2030-01-01T12:02:00Z
```

Unknown, partial, expired, inverted, nonce/profile/first-hop/version mismatch,
self-hash forgery, duplicate/unknown JSON, non-integer JSON number, BOM,
malformed UTF-8, symlink, traversal, or sensitive credential reference fails
closed. The typed attestation requests have no caller command, argv, shell,
PowerShell, script, path fragment, or caller-selected retry surface;
`automatic_retry` is fixed to `false`.

Validation is stateless and idempotent. Revalidating the same artifact inside
its valid time window returns the same result; PR2 neither consumes the nonce
nor claims replay suppression. Single-use/replay enforcement belongs to PR3
authorization plus the future PR4/PR6 trusted live owner immediately before a
mutation. Every PR2 receipt remains `no_execution_authorization=true`.

In a nested receipt, `host_key_evidence_sha256` binds the approved second-hop
host-key evidence projection from TransportIdentityBinding. It is not an
observed second-hop fingerprint. Per the accepted RFC, the actual second-hop
handshake and observed-fingerprint comparison happen only after the hash-only
receipt validates and remain future live-adapter work. Consequently,
`classification=verified` does not claim that handshake occurred.

## PR4B prerequisite successor

Published PR2 `/1` artifacts remain unchanged and replay-only. The separate
offline owner `transport_authority_closure.py` adds `execution-profile/2`, in
which first-hop and second-hop adapter config references are represented only
by fixed logical roles and nonzero digests. It also adds permanent
non-authorizing `execution-request/2`; `execution-authorization/2` must
reference that exact request rather than treating request `/1` as new intent.
The handshake owner consumes actual PR2-owner-validated Stage A/B artifacts,
computes their canonical receipt digests, validates a separate observation
against the approved second-hop evidence, and only then validates a fixed
single-attempt, zero-retry receipt. These contracts perform no
handshake and authorize no stage, submit, cancel, fetch or arbitrary command.
