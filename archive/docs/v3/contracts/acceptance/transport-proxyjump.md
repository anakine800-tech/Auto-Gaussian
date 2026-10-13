# Auto-G16 v3 acceptance: transport-proxyjump

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:1882-1930 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01 acceptance

1. The exact Option-1 config inventory resolves only the Mac OpenSSH ProxyJump
   route. Missing, additional, mixed legacy, malformed, or target-spliced
   config fails before process creation; no architecture fallback exists.
2. The manifest binds `/usr/bin/ssh`, 1584576 bytes, SHA-256
   `17542914a3fb55e7efeb35a90d594a21c84bf6a4cfe1fc8ddff5606dc2658fc3`.
   Path, size, digest, executable identity, and all four config artifacts are
   attested before and after each invocation.
3. The config has exactly the reviewed RTwin and final-server aliases,
   addresses, ports, users, distinct absolute identity references, explicit
   known-hosts paths, one final public-key fingerprint, `ProxyJump`, and the
   full closed authentication directive set. `ProxyCommand`, ForwardAgent,
   global config mutation, implicit known_hosts, TOFU, extra hosts, password,
   keyboard-interactive, GSSAPI, and hostbased authentication reject. The
   dedicated canonical ED25519 public-key artifact must calculate to the exact
   fingerprint bound by the config. Both host blocks require exact
   `CertificateFile none`; removal or any certificate-file value rejects, so
   OpenSSH cannot auto-load an unbound `IdentityFile-cert.pub` sibling.
4. Both private identity references must be non-symlink regular files owned by
   the current user with mode `0600`. The final private identity must also match
   its profile-bound device/inode/size/mtime/ctime tuple. Product code obtains
   private-file metadata only and never opens, reads, hashes, copies, logs, or
   persists private key bytes. Wrong public bytes, fingerprint, private-file
   identity, ownership, or mode reject before process creation.
5. The process argv uses only exact `/usr/bin/ssh -F <bound-config> --
   <bound-final-alias> <existing-server-command>`, with `shell=False`. It has no
   Windows PowerShell, RTwin launcher, `-J`, ProxyCommand, or direct-server
   fallback surface.
6. The complete exact AGV3 request frame is passed once to Mac OpenSSH stdin;
   existing binary EOF propagation, bounded stdout/stderr collection, process
   ownership, and strict response decoding are reused unchanged. Canonical JSON,
   protocol, operation, status/result, and binding failures still reject.
7. Existing TransportStore, physical binding, Torque rendering, resource sole
   authority, qsub-at-most-once, WINNER, REPLAY-zero-effect, UNKNOWN-no-retry,
   scheduler/fetch/capture, and V30-A synthetic composition tests remain PASS.
8. Narrow reuse is `KEEP` for protocol/store/bootstrap/authority owners,
   `WRAP` for the bounded subprocess supervisor, `PORT` for qualified Mac
   OpenSSH/config/trust/identity references, and `REPLACE` only for the route
   selected by the new profile. No new generic transport framework or public
   symbol is introduced.
9. ServerProfile revision 8 resolves a new exact identity and effective digest.
   Prior profiles and Windows-route evidence remain immutable and cannot
   authorize the Option-1 route.
10. Focused and affected validation pass once per frozen candidate and an
    independent adversarial review reports `P0/P1/P2/P3 = 0/0/0/0`. Product
    integration, PR, CI, and normal merge perform zero deployment, Attempt,
    workspace, qstat, qsub, Gaussian, qdel, cleanup, or automatic retry.
