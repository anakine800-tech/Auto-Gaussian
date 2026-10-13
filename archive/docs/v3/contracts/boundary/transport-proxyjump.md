# Auto-G16 v3 boundary: transport-proxyjump

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:4779-4824 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01 boundary

The selected successor execution chain is Controller -> exact buffered AGV3
frame -> exact Mac `/usr/bin/ssh` -> one config-bound `ProxyJump` through RTwin
-> final server -> unchanged fixed bootstrap. RTwin is only the jump-host SSH
endpoint and direct-tcpip forwarder. It does not consume AGV3 stdin,
authenticate to the final server, or hold the final-server private key.

Route selection is closed and private. An exact Option-1 config inventory
selects `mac-openssh-proxyjump-v1`; the prior exact four-file inventory selects
only the historical Windows route. A mixed, incomplete, or additional inventory
rejects. Option-1 never falls back to Windows nested SSH, STARTUPINFOEX,
ProxyCommand, direct Mac-to-server, or the old RTwin launcher.

The Option-1 config has exactly two closed host blocks, one calculated final-key
fingerprint comment, and one frozen final private-file physical-identity
comment. It binds the one RTwin jump identity and known-hosts file,
the distinct dedicated final-server identity and known-hosts file, the exact
target identities already present in the resolved ServerProfile, and all
frozen authentication restrictions. The four config artifacts, including the
dedicated final public key, and `/usr/bin/ssh` are attested before and after the
process. The public key is strict canonical ED25519 and its calculated
fingerprint must equal the config binding. Each private identity reference is
a current-user-owned, non-symlink regular file with exact mode `0600`; the final
identity must also match the frozen device/inode/size/mtime/ctime tuple. Private
content is never opened or read. Exact `CertificateFile none` is mandatory in
both host blocks, disabling OpenSSH's implicit sibling user-certificate lookup.

The final argv is exactly the attested executable, `-F`, the bound private
config path, `--`, the bound final alias, and the existing quoted server
bootstrap command. Variable argv positions reject NUL, CR, and LF. LF is
permitted only inside the already identity-gated fixed bootstrap source word.
Process creation remains `shell=False`; the existing bounded binary
stdin/stdout/stderr supervisor and strict response decoder are reused.

ServerProfile revision 8 binds the qualified OpenSSH 10.3p1 executable,
Option-1 config/trust identities, exact final public-key fingerprint, unchanged
ten-root manifest schema, unchanged Torque/resource descriptor, and unchanged
bootstrap/table bytes. It resolves as
`44f3b829-e2d1-5500-b463-5acd8851d279` with effective config SHA-256
`110bac5e2fbcecd2a01a81f8df5004f797cb191b2089b620b4379db28a7cb99d`;
the new 3294-byte manifest SHA-256 is
`bf422724e83cc16031136783fb042207959cb0cd7f602e7d0f63df787350019e`.
No public Execution/Transport API or schema changes.
Deployment and every calculation effect remain separate Owner gates.
