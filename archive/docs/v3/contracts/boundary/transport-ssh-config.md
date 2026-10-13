# Auto-G16 v3 boundary: transport-ssh-config

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:4317-4506 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01

### Exact profile-bound configuration inventory

The RTwin live-capable driver must enact the same SSH configuration bytes that
the existing public Execution resolver freezes into the snapshot. The private
Transport convention uses these exact names:

| Hop | `platform_paths` config key | `config_files` config name | `platform_paths` known-hosts key | `config_files` known-hosts name |
| --- | --- | --- | --- | --- |
| Mac to RTwin | `mac_ssh_config_path` | `mac-ssh-config` | `mac_known_hosts_path` | `mac-known-hosts` |
| RTwin to server | `rtwin_ssh_config_path` | `rtwin-ssh-config` | `rtwin_known_hosts_path` | `rtwin-known-hosts` |

All four path keys are mandatory for a Transport operation. Its complete
`config_files` logical-name set is exactly the four names in the table, with
one occurrence each; no fifth unrelated or legacy name is accepted by
Transport. This exact-set rule does not narrow the generic Execution resolver.
No alias, fallback lookup, ambient config, or independently supplied byte/path
input exists. Mac paths are canonical absolute POSIX paths;
RTwin paths are canonical absolute Windows paths. Config and known-host bytes
remain non-secret profile content. Dedicated private-key paths may appear only
inside the configs; private-key bytes and digests are neither read nor bound.
The four effect paths and both config `IdentityFile` values reject `%`, `$`,
`~`, `*`, `?`, `[`, `]`, `{`, and `}`. Therefore OpenSSH token,
environment-variable, home, or glob expansion cannot select a different file
than the exact literal path that Transport attests. A Windows backslash is a
literal path separator, never escape syntax.

### Closed SSH config grammar

The source-reviewed grammar is deliberately narrower than OpenSSH. Config
bytes decode as strict UTF-8 without BOM, contain no NUL, CR, or HTAB, and end
in exactly one LF; therefore the final split line is empty. A non-final empty
line is blank. A comment line starts with `#` in column one. Every other
physical line matches exactly `^ *[A-Za-z][A-Za-z0-9]* [^ ]+$`: zero or more
leading ASCII SP, one directive, exactly one separating SP, one nonempty value,
and no trailing SP. Quote, backslash, inline comment, escape, and continuation
syntax do not exist. Directive spelling and the literal value `yes` are
case-sensitive and exactly as shown below.

The first semantic line is exactly `Host A`, where alias `A` matches
`[A-Za-z0-9][A-Za-z0-9._-]*`; it is the only `Host` line and contains one
alias. After it, exactly one each of `HostName`, `User`, `IdentityFile`, `IdentitiesOnly`,
`StrictHostKeyChecking`, and `UserKnownHostsFile` is required; `Port` occurs
zero or one time. No other directive is legal.

`IdentitiesOnly` and `StrictHostKeyChecking` equal `yes`; `IdentityFile` is one
dedicated absolute path for that platform; `UserKnownHostsFile` equals the
corresponding bound path; and an omitted port resolves to 22. The Mac alias
must reproduce the sole resolved RTwin hop. The RTwin alias must reproduce the
resolved server destination. This excludes `Include`, `Match`/`exec`,
`ProxyCommand`, `ProxyJump`, command hooks, every forwarding directive,
known-host commands, providers, agent overrides, and any config that redirects
host, user, or port. An additional proxy hop has no first-live authority.

### Exact command and attestation seam

The outer structured argv begins with exact manifest `mac_ssh`, then exact
`-F mac_ssh_config_path`. The inner manifest-bound PowerShell launch invokes
exact `rtwin_ssh` with exact `-F rtwin_ssh_config_path`. Both commands
explicitly set `BatchMode=yes`, `IdentitiesOnly=yes`,
`StrictHostKeyChecking=yes`, `IdentityAgent=none`,
`PreferredAuthentications=publickey`, `PubkeyAuthentication=yes`,
`PasswordAuthentication=no`, and `KbdInteractiveAuthentication=no`. Both set
`GSSAPIAuthentication=no`, `HostbasedAuthentication=no`,
`VerifyHostKeyDNS=no`, and `UpdateHostKeys=no`. Both set
`UserKnownHostsFile` and `GlobalKnownHostsFile` to the same hop-specific bound
known-hosts path, closing additional ambient host-key sources. The destination
token is the exact validated Host alias; explicit port/user values equal the
resolved profile. Local argv remains structured with `shell=False`; no caller
option, config path, target, shell fragment, or credential enters it.

For exact values `MC`, `MK`, `MA`, `MP`, `MU`, and generated PowerShell script
`PS`, the complete ordered outer argv is:

```text
(mac_ssh,
 "-F", MC,
 "-o", "BatchMode=yes",
 "-o", "IdentitiesOnly=yes",
 "-o", "StrictHostKeyChecking=yes",
 "-o", "UserKnownHostsFile=" + MK,
 "-o", "GlobalKnownHostsFile=" + MK,
 "-o", "IdentityAgent=none",
 "-o", "PreferredAuthentications=publickey",
 "-o", "PubkeyAuthentication=yes",
 "-o", "PasswordAuthentication=no",
 "-o", "KbdInteractiveAuthentication=no",
 "-o", "GSSAPIAuthentication=no",
 "-o", "HostbasedAuthentication=no",
 "-o", "VerifyHostKeyDNS=no",
 "-o", "UpdateHostKeys=no",
 "-p", canonical_decimal(MP),
 "-l", MU,
 "--", MA, PS)
```

For exact values `RC`, `RK`, `RA`, `RP`, `RU`, and exact bootstrap command
`BC`, the ordered RTwin child argv encoded by the frozen CRT/PowerShell
launcher is:

```text
(rtwin_ssh,
 "-F", RC,
 "-o", "BatchMode=yes",
 "-o", "IdentitiesOnly=yes",
 "-o", "StrictHostKeyChecking=yes",
 "-o", "UserKnownHostsFile=" + RK,
 "-o", "GlobalKnownHostsFile=" + RK,
 "-o", "IdentityAgent=none",
 "-o", "PreferredAuthentications=publickey",
 "-o", "PubkeyAuthentication=yes",
 "-o", "PasswordAuthentication=no",
 "-o", "KbdInteractiveAuthentication=no",
 "-o", "GSSAPIAuthentication=no",
 "-o", "HostbasedAuthentication=no",
 "-o", "VerifyHostKeyDNS=no",
 "-o", "UpdateHostKeys=no",
 "-p", canonical_decimal(RP),
 "-l", RU,
 "--", RA, BC)
```

For a synthetic RTwin config path `C:\cfg\server`, known-host path
`C:\cfg\server-known`, alias `server-a`, port `22`, user `server-user`, and
bootstrap command `BOOTSTRAP`, the complete child token tuple after the exact
`rtwin_ssh` executable is:

```text
"-F","C:\cfg\server","-o","BatchMode=yes","-o","IdentitiesOnly=yes",
"-o","StrictHostKeyChecking=yes",
"-o","UserKnownHostsFile=C:\cfg\server-known",
"-o","GlobalKnownHostsFile=C:\cfg\server-known",
"-o","IdentityAgent=none","-o","PreferredAuthentications=publickey",
"-o","PubkeyAuthentication=yes","-o","PasswordAuthentication=no",
"-o","KbdInteractiveAuthentication=no","-o","GSSAPIAuthentication=no",
"-o","HostbasedAuthentication=no","-o","VerifyHostKeyDNS=no",
"-o","UpdateHostKeys=no","-p","22","-l","server-user","--",
"server-a","BOOTSTRAP"
```

The exact PowerShell `Arguments` value is the single-SP join of
`crt_quote_v1(token)` for that ordered tuple. The existing frozen CRT quoting
grammar is reused; no other joiner, combined option, or destination placement
is conforming.

`canonical_decimal` is ASCII base-10 with no sign or leading zero. For a
synthetic Mac config path `/cfg/mac`, known-host path `/cfg/mac-known`, alias
`rtwin-a`, port `22`, and user `rtwin-user`, the outer tokens from `-F` through
the destination are exactly:

```text
"-F","/cfg/mac","-o","BatchMode=yes","-o","IdentitiesOnly=yes",
"-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile=/cfg/mac-known",
"-o","GlobalKnownHostsFile=/cfg/mac-known","-o","IdentityAgent=none",
"-o","PreferredAuthentications=publickey","-o","PubkeyAuthentication=yes",
"-o","PasswordAuthentication=no","-o","KbdInteractiveAuthentication=no",
"-o","GSSAPIAuthentication=no","-o","HostbasedAuthentication=no",
"-o","VerifyHostKeyDNS=no","-o","UpdateHostKeys=no",
"-p","22","-l","rtwin-user","--","rtwin-a"
```

For every platform path and both config `IdentityFile` values, any `%`, `$`,
`~`, `*`, `?`, bracket, or brace character rejects before command
construction. Negative fixtures include `/cfg/%h`, `/cfg/${HOME}`,
`~/.ssh/id`, `C:\cfg\%h`, and `C:\cfg\${HOME}`.

The private deployment authority produced by
`_resolve_deployment_authority(snapshot, current_profile)` carries only parsed
mechanical config evidence after public profile/snapshot equality succeeds.
Before local process creation, controller-file attestation opens the exact Mac
config and known-host files no-follow, requires regular-file identity, and
compares exact size and SHA-256 with `config_files`. A prelaunch failure creates
zero subprocess. After process completion it reopens and requires the same
descriptor/name identity and bytes; postlaunch drift rejects the child result
and, if an effect may have crossed, preserves `UNKNOWN` with no retry. The
PowerShell launcher requires non-directory, non-reparse exact size/SHA-256 for
RTwin config and known-hosts immediately before nested SSH and after the nested
process terminates. A prelaunch RTwin mismatch creates zero nested SSH. A
postlaunch RTwin drift makes the result unusable and preserves `UNKNOWN` where
applicable. No mismatch retries or switches files.

These four files do not change the exact nine-root deployment manifest. They
close effect configuration through the already identity-bound ServerProfile.
The pre-repair resolved profile is unusable for live authority. Integration
requires a new profile revision/resolution before Phase 7 of the live packet
may pass, and no Attempt may be created under the stale identity. This contract
changes no public Core, Approval, Workflow, Execution, Observe, Result,
ScientificValidation, or Review API/schema and authorizes no live effect.
