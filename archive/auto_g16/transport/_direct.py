"""Closed Mac-direct profile; no discovery, configuration writes or fallback."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
import os
import re
import stat
from typing import TYPE_CHECKING

from ._canonical import TransportBoundaryError

if TYPE_CHECKING:
    from ._driver import _BoundEffectFile, _SSHConfigTarget

_DIRECT_CONFIG_PATHS = {
    "mac-direct-ssh-config": "mac_direct_ssh_config_path",
    "mac-direct-known-hosts": "mac_direct_known_hosts_path",
    "mac-direct-public-key": "mac_direct_public_key_path",
}
# Candidate executable binding, not a claim of direct-route qualification.
_DIRECT_MAC_SSH = (
    "/usr/bin/ssh", 1_584_576,
    "17542914a3fb55e7efeb35a90d594a21c84bf6a4cfe1fc8ddff5606dc2658fc3",
)
_DIRECT_FIXED = {
    "IdentitiesOnly": "yes", "IdentityAgent": "none", "CertificateFile": "none",
    "PreferredAuthentications": "publickey", "PubkeyAuthentication": "yes",
    "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
    "GSSAPIAuthentication": "no", "HostbasedAuthentication": "no",
    "StrictHostKeyChecking": "yes", "GlobalKnownHostsFile": "/dev/null",
    "UpdateHostKeys": "no", "VerifyHostKeyDNS": "no", "WarnWeakCrypto": "no",
    "ForwardAgent": "no", "RequestTTY": "no", "BatchMode": "yes",
    "CanonicalizeHostname": "no", "ControlMaster": "no", "ControlPath": "none",
    "ControlPersist": "no", "ConnectionAttempts": "1",
}


@dataclass(frozen=True, slots=True)
class _MacDirectEffectAuthority:
    route: str
    config: _BoundEffectFile
    final_known_hosts: _BoundEffectFile
    final_public_key: _BoundEffectFile
    final_identity_fingerprint: str
    final_identity_file_identity: tuple[int, int, int, int, int]
    final_target: _SSHConfigTarget


def _component_identity(value):
    # Directory timestamps change on unrelated child creation; physical identity,
    # type, permissions and ownership are the retained routing components.
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


@contextmanager
def _direct_parent(path):
    """Walk from / using pinned directory descriptors; never resolve symlinks."""
    parts = path.split("/")
    if parts[0] != "" or any(part in {"", ".", ".."} for part in parts[1:]):
        raise TransportBoundaryError("Direct local path is not canonical absolute")
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptors.append(os.open("/", flags))
        chain = [_component_identity(os.fstat(descriptors[-1]))]
        for part in parts[1:-1]:
            parent = descriptors[-1]
            descriptors.append(os.open(part, flags, dir_fd=parent))
            opened = os.fstat(descriptors[-1])
            named = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(opened.st_mode) or _component_identity(opened) != _component_identity(named):
                raise TransportBoundaryError("Direct directory component drifted")
            chain.append(_component_identity(opened))
        yield descriptors[-1], parts[-1], tuple(chain)
    except OSError as exc:
        raise TransportBoundaryError("Direct no-follow local path is unavailable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _direct_private_identity(effect):
    with _direct_parent(effect.final_target.identity_file) as (parent, leaf, chain):
        value = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode) or stat.S_IMODE(value.st_mode) != 0o600 or value.st_uid != os.getuid():
            raise TransportBoundaryError("Direct private identity reference is unsafe")
        identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity != effect.final_identity_file_identity:
            raise TransportBoundaryError("Direct private identity metadata drifted")
        return chain, identity


def _attest_direct_readable(bound, protected, *, executable=False):
    with _direct_parent(bound.path) as (parent, leaf, chain):
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        descriptor = os.open(leaf, flags, dir_fd=parent)
        try:
            opened = os.fstat(descriptor)
            # MUST precede every read, including the EOF probe. String paths,
            # expected size and hashes cannot establish private-key isolation.
            if (opened.st_dev, opened.st_ino) == protected:
                raise TransportBoundaryError("Direct readable artifact aliases protected private identity")
            named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
                    or _component_identity(opened) != _component_identity(named)
                    or opened.st_size != bound.expected_size_bytes
                    or (executable and opened.st_mode & 0o111 == 0)):
                raise TransportBoundaryError("Direct readable artifact identity drifted")
            digest, remaining = sha256(), opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    raise TransportBoundaryError("Direct readable artifact read was short")
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1) or digest.hexdigest() != bound.expected_sha256:
                raise TransportBoundaryError("Direct readable artifact bytes drifted")
            after = os.fstat(descriptor)
            identity = lambda value: (*_component_identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if identity(after) != identity(opened):
                raise TransportBoundaryError("Direct readable artifact changed during read")
            return chain, identity(opened)
        finally:
            os.close(descriptor)


def _attest_direct_executable(root, protected):
    return _attest_direct_readable(root, protected, executable=True)


def _attest_direct_local(authority):
    """One Direct-only ordering for normal and reconciliation process owners."""
    effect = authority.ssh_effect
    if type(effect) is not _MacDirectEffectAuthority:
        raise TransportBoundaryError("Direct local attestation requires exact authority")
    private = _direct_private_identity(effect)
    protected = private[1][:2]
    result = {"private": private}
    for bound in (effect.config, effect.final_known_hosts, effect.final_public_key):
        result[bound.name] = _attest_direct_readable(bound, protected)
    result["mac_ssh"] = _attest_direct_executable(authority.manifest.trust_roots["mac_ssh"], protected)
    if _direct_private_identity(effect) != private:
        raise TransportBoundaryError("Direct private path changed during attestation")
    # Re-walk all readable routing chains after hashing. The process owners also
    # compare this complete state before/after the invocation. OpenSSH's later
    # pathname reopening remains a separately qualified native boundary.
    for bound in (effect.config, effect.final_known_hosts, effect.final_public_key, authority.manifest.trust_roots["mac_ssh"]):
        with _direct_parent(bound.path) as (parent, leaf, chain):
            named = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            identity = (*_component_identity(named), named.st_size, named.st_mtime_ns, named.st_ctime_ns)
            if (chain, identity) != result[bound.name]:
                raise TransportBoundaryError("Direct local path changed during attestation")
    return result


def _resolve_mac_direct(profile, current) -> _MacDirectEffectAuthority:
    from ._driver import _BoundEffectFile, _closed_effect_path

    names = [name for name, _ in profile.config_files]
    if len(names) != 3 or set(names) != set(_DIRECT_CONFIG_PATHS):
        raise TransportBoundaryError("Mac direct config inventory must be exact")
    paths = current.platform_paths
    # Program executable/data paths are independent; route-specific paths cannot mix.
    foreign = {"mac_ssh_config_path", "mac_known_hosts_path", "mac_proxyjump_ssh_config_path",
               "mac_rtwin_known_hosts_path", "mac_final_known_hosts_path", "mac_final_public_key_path"}
    if foreign.intersection(paths) or any(key.startswith("rtwin_") for key in paths):
        raise TransportBoundaryError("Mac direct profile contains another route's paths")
    contents = dict(profile.config_files)
    bound = {}
    for name, key in _DIRECT_CONFIG_PATHS.items():
        try:
            path = _closed_effect_path(paths[key], "macos", key)
        except KeyError as exc:
            raise TransportBoundaryError("Mac direct effect paths are incomplete") from exc
        if any(c in path for c in '\\"\' #'):
            raise TransportBoundaryError("Mac direct path contains SSH quoting syntax")
        raw = contents[name]
        if type(raw) is not bytes or not raw:
            raise TransportBoundaryError("Mac direct artifact bytes are invalid")
        bound[name] = _BoundEffectFile(name, path, "macos", sha256(raw).hexdigest(), len(raw))
    if len({item.path for item in bound.values()}) != 3:
        raise TransportBoundaryError("Mac direct artifact paths must be distinct")
    return _parse_mac_direct_config(contents["mac-direct-ssh-config"], bound=bound,
                                    public_key=contents["mac-direct-public-key"], current=current)


def _parse_mac_direct_config(raw: bytes, *, bound, public_key: bytes, current) -> _MacDirectEffectAuthority:
    from ._driver import _SSHConfigTarget, _closed_effect_path, _parse_openssh_ed25519_public_identity

    if (type(raw) is not bytes or not raw or raw.startswith(b"\xef\xbb\xbf")
            or any(char in raw for char in (b"\x00", b"\r", b"\t"))
            or not raw.endswith(b"\n") or raw.endswith(b"\n\n")):
        raise TransportBoundaryError("Mac direct config byte grammar is invalid")
    try:
        lines = raw[:-1].decode("utf-8", errors="strict").split("\n")
    except UnicodeDecodeError as exc:
        raise TransportBoundaryError("Mac direct config must be UTF-8") from exc
    fingerprint = _parse_openssh_ed25519_public_identity(public_key)
    if len(lines) < 3 or lines[0] != f"# AutoG16DirectIdentityFingerprint {fingerprint}":
        raise TransportBoundaryError("Mac direct public fingerprint differs")
    match = re.fullmatch(r"# AutoG16DirectIdentityFileIdentity ([0-9]+):([0-9]+):([0-9]+):([0-9]+):([0-9]+)", lines[1])
    if match is None:
        raise TransportBoundaryError("Mac direct private file metadata is invalid")
    identity = tuple(int(value) for value in match.groups())
    fields = {}
    for index, line in enumerate(lines[2:]):
        match = re.fullmatch(r"Host ([A-Za-z0-9][A-Za-z0-9._-]*)" if index == 0 else r"    ([A-Za-z][A-Za-z0-9]*) ([^\s]+)", line)
        if match is None:
            raise TransportBoundaryError("Mac direct config line grammar is invalid")
        key, value = ("Host", match.group(1)) if index == 0 else match.groups()
        if key in fields:
            raise TransportBoundaryError("Mac direct duplicate directive")
        fields[key] = value
    required = set(_DIRECT_FIXED) | {"Host", "HostName", "Port", "User", "IdentityFile", "UserKnownHostsFile"}
    if set(fields) != required or any(fields[key] != value for key, value in _DIRECT_FIXED.items()):
        raise TransportBoundaryError("Mac direct directive inventory/security values differ")
    target = current.target_identity
    if target["jump_topology"]:
        raise TransportBoundaryError("Mac direct requires empty jump topology")
    if (fields["HostName"], fields["Port"], fields["User"]) != (
            target["destination_host"], str(target["destination_port"]), current.remote_user):
        raise TransportBoundaryError("Mac direct target differs from profile")
    if fields["UserKnownHostsFile"] != bound["mac-direct-known-hosts"].path:
        raise TransportBoundaryError("Mac direct known-hosts differs from profile")
    private_path = _closed_effect_path(fields["IdentityFile"], "macos", "Mac direct IdentityFile")
    if any(c in private_path for c in '\\"\' #'):
        raise TransportBoundaryError("Mac direct identity path contains SSH quoting syntax")
    if private_path in {item.path for item in bound.values()}:
        raise TransportBoundaryError("Mac direct private reference aliases a readable artifact")
    return _MacDirectEffectAuthority(
        "mac-openssh-direct-v1", bound["mac-direct-ssh-config"], bound["mac-direct-known-hosts"],
        bound["mac-direct-public-key"], fingerprint, identity,
        _SSHConfigTarget(fields["Host"], fields["HostName"], int(fields["Port"]), fields["User"], private_path),
    )


def _build_mac_direct_command(scope, authority, *, source: bytes) -> tuple[str, ...]:
    from . import _bridge, _submission_recovery
    from ._driver import _DeploymentAuthority
    from auto_g16.execution import ResolvedServerProfile
    from auto_g16.execution.program import ProgramExecutionSnapshot

    if type(scope) is ProgramExecutionSnapshot:
        scope.assert_identity_closed()
        profile, scope_id = scope.resolved_server_profile, scope.program_execution_snapshot_id
    elif type(scope) is ResolvedServerProfile:
        scope.assert_identity_closed()
        profile, scope_id = scope, scope.resolved_server_profile_id
    else:
        raise TransportBoundaryError("Mac direct requires closed program or Project scope")
    if type(authority) is not _DeploymentAuthority or type(authority.ssh_effect) is not _MacDirectEffectAuthority:
        raise TransportBoundaryError("Mac direct requires exact Direct authority")
    effect, manifest = authority.ssh_effect, authority.manifest
    ssh = manifest.trust_roots["mac_ssh"]
    if (effect.route != "mac-openssh-direct-v1" or profile.target_identity["jump_topology"]
            or authority.execution_snapshot_id != scope_id
            or authority.resolved_server_profile_id != profile.resolved_server_profile_id
            or authority.effective_config_sha256 != profile.effective_config_sha256
            or manifest.schema != "auto-g16-v3-transport-deployment-manifest/3"
            or (ssh.path, ssh.expected_size_bytes, ssh.expected_sha256) != _DIRECT_MAC_SSH
            or manifest.sha256 != sha256(manifest.raw_bytes).hexdigest()
            or manifest.size_bytes != len(manifest.raw_bytes)
            or (authority.bootstrap_source_sha256, authority.bootstrap_source_size_bytes) !=
               (sha256(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(), len(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))):
        raise TransportBoundaryError("Mac direct deployment differs from scope")
    # Recovery source selection still requires the existing collection/recovery owner.
    if type(source) is not bytes or source not in (_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES, _submission_recovery.source_bytes()):
        raise TransportBoundaryError("Mac direct bootstrap must be fixed source bytes")
    server_command = _bridge._render_program_server_command(authority, source)
    command = (ssh.path, "-F", effect.config.path, "--", effect.final_target.alias, server_command)
    if any(type(token) is not str or any(c in token for c in "\x00\r\n") for token in command[:-1]) or any(c in server_command for c in "\x00\r"):
        raise TransportBoundaryError("Mac direct command contains invalid characters")
    return command
