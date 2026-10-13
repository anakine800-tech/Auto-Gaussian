# Auto-G16 MAC-DIRECT-UNMANAGED-V1

## Authorization and identity

Owner-guided v3 feature development, non-BUS, L3 transport/process boundary.
On 2026-10-13 the Owner chose, in conversation, to reuse the qualified
Option-1 ProxyJump process owner for a Mac-to-final-server route without the
RTwin hop, accepting that the managed native guarantees below are not provided.
That decision is recorded as
[OD-46](../../../OWNER_DECISIONS.md#od-46-unmanaged-mac-direct-reuses-the-option-1-process-owner).

Base: `main` commit `fe28c26aa373b3a3237e1eb80ab24c2372f62380`, tree
`200319525fe109f50a0849a6bb98284590444440`. Branch:
`codex/mac-direct-unmanaged-v1`.

Authorized in this task: this contract, OD-46, implementation in the four
Transport files named below, offline tests, the example SSH config, boundary/
acceptance/context-map documentation, offline validation and a local commit.
Not authorized: SSH/network contact, RTwin, PBS, qsub, xTB/CREST/Gaussian
execution, installation or publisher qualification of a new profile, push,
PR, merge, deployment, cleanup or retry of any Attempt.

## Route

Route identity `mac-openssh-direct-unmanaged-v1`. It is selected only by the
exact three-artifact inventory:

| Logical config file | ServerProfile platform path key |
| --- | --- |
| `mac-unmanaged-direct-ssh-config` | `mac_unmanaged_direct_ssh_config_path` |
| `mac-unmanaged-direct-known-hosts` | `mac_unmanaged_direct_known_hosts_path` |
| `mac-unmanaged-direct-public-key` | `mac_unmanaged_direct_public_key_path` |

`jump_topology` must be empty. Any additional, missing or mixed inventory
rejects, including any managed `mac-direct-*`, Option-1, legacy Mac/RTwin
or `rtwin_*` path key. This route is never a fallback from Option-1 and Option-1
is never a fallback from it: each profile names exactly one route and a
failure stops with the existing Transport error. The managed
`mac-openssh-direct-v1` route, its authority type and its closed
`run_direct()` entry are unchanged and still reject unconditionally.

The SSH config grammar is the existing closed Direct grammar in
`auto_g16/transport/_direct.py`: two binding comments (public-key fingerprint
and private-file device/inode/size/mtime/ctime), one `Host` block, exactly the
fixed security directives plus `HostName`, `Port`, `User`, `IdentityFile` and
`UserKnownHostsFile`. `ProxyJump`, `ProxyCommand`, `Include`, `Match`,
forwarding, agents, passwords, certificates, TOFU and connection sharing are
impossible by construction. Host, port and user must equal the resolved
profile target. See `config/mac_unmanaged_direct_ssh_config.example`.

The OpenSSH executable must be the Option-1 qualified identity
(`/usr/bin/ssh`, 1584576 bytes, SHA-256
`17542914a3fb55e7efeb35a90d594a21c84bf6a4cfe1fc8ddff5606dc2658fc3`). A
different macOS build needs its own reviewed identity change; there is no
configuration override.

## Process and effect boundary

The route uses the same process owners as Option-1:
`_SubprocessRTWinDriver._run` for normal and collection operations and
`_RecoveryProcessOwner._run` for exact reconciliation. Both create one
`subprocess.Popen` with the fixed absolute argv `ssh -F <config> -- <alias>
<server command>`, `shell=False`, `start_new_session=True`, the fixed
environment, bounded stdin/stdout/stderr and process-group kill on timeout or
cap. The server command is the identical Program bootstrap rendering Option-1
uses for the same manifest and source (xTB, CREST and Gaussian successors).

Before the process and again after it, the controller runs the Direct local
attestation: no-follow descriptor walks from `/`, exact size/SHA-256 of the
config, known-hosts, public key and `ssh`, private-key metadata only
(current-UID owned, mode `0600`, frozen identity tuple, never opened or read),
no readable artifact aliasing the private inode, and an identical before/after
chain. Because every directory component is opened without following links,
all four paths must be canonical real paths (for example under
`/Users/<user>/`, not `/tmp` or `/var`, which are symlinks on macOS). Drift returns the existing `transport-error` / `identity-drift` result
and never retries.

Unchanged and still binding: Scientific Approval, Batch Submit Approval,
ExecutionSnapshot and Exact Operational Confirmation; one Core WINNER and at
most one `qsub` per Attempt; `UNKNOWN` reconciliation without automatic retry;
`REPLAY` with zero wire effects; Attempt no-overwrite; Project provisioning
through `_RTWinProjectAttestor`; fixed publisher/collection installation reads;
synthetic executables rejected by the production driver.

## Guarantees not provided

Compared with MAC-DIRECT-MANAGED-NATIVE-V1 this route does not provide:

- a single native child owner with suspended `posix_spawn`, `EVFILT_PROC`
  FORK/EXEC observation, non-reaping `waitid` and exactly one reap;
- a separate executor UID, LaunchDaemon, IPC peer authentication or durable
  lifecycle veto; the desktop UID that runs the controller holds the
  final-server private key and launches `ssh`;
- descendant tracking beyond the existing process-group kill.

These are the same process and key-custody properties the production Option-1
route already has; only the RTwin hop is removed. Server reachability, host-key
pinning and account restrictions on the final server become the Owner's
responsibility for this route.

## Validation and acceptance

Offline only. Required evidence:

1. Route selection: exact inventory selects the unmanaged authority; managed,
   Option-1 and legacy inventories keep their routes; mixed/extra/missing
   artifacts, non-empty jump topology, target mismatch, forbidden directives,
   wrong fingerprint and wrong `ssh` identity reject.
2. Command: argv equals Option-1 shape with the Direct alias and config; the
   server command equals the Option-1 rendering for the same authority.
3. Process owner: one `Popen` with `shell=False`, `start_new_session=True` and
   fixed environment; attestation runs before and after; drift reports
   transport error; the managed `run_direct` is never called.
4. Production chain with an offline wire peer: Project provisioning,
   allocate/stage/submit once, scheduler query, capture, terminal replay
   without a second wire effect, and `UNKNOWN` reconciliation without a second
   `qsub`.
5. Existing managed native/offline, Option-1 and V31 transport suites pass.

Live use requires a separate explicit Owner gate: the Owner first confirms
manual reachability of the final server from the Mac; a new profile then needs
its own publisher installation and qualification evidence (qualification of
the Option-1 profile does not transfer), followed by one approved xTB smoke
under the normal three-gate approval and the XTB-FLOW-01 acceptance shape.
CREST and Gaussian need their own later smoke evidence.
