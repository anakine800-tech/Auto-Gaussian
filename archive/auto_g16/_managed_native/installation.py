"""Closed installation description, never installation authenticity evidence."""

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from auto_g16._managed_offline.common import Rejected, exact, json_bytes


@dataclass(frozen=True, slots=True)
class Installation:
    installation_id: str
    executor_uid: int
    desktop_uid: int
    description_sha256: str
    root: str
    state: str
    ipc: str


def parse_description(raw):
    """Data-only parse; no caller-supplied trust/qualified/activation fields."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 16384:
        raise Rejected("INSTALLATION_DESCRIPTION")
    try:
        value = json.loads(raw)
        if json_bytes(value) != raw:
            raise ValueError
        exact(value, ("schema", "installation_id", "executor_uid", "desktop_uid"))
        if value["schema"] != "auto-g16-managed-installation-description/1":
            raise ValueError
        name = value["installation_id"]
        if type(name) is not str or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", name) is None:
            raise ValueError
        uid, desktop = value["executor_uid"], value["desktop_uid"]
        if any(type(n) is not int or not 1 <= n <= 4294967294 for n in (uid, desktop)) or uid == desktop:
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise Rejected("INSTALLATION_DESCRIPTION") from exc
    return Installation(name, uid, desktop, sha256(raw).hexdigest(),
                        "/Library/AutoG16/installations/" + name,
                        "/private/var/db/auto-g16/" + name,
                        "/Library/AutoG16/ipc/" + name)


def require_qualified_installation():
    # There is intentionally no accepted manifest, boolean, environment variable,
    # test adapter or development identity that can make this return successfully.
    raise Rejected("NATIVE_NOT_QUALIFIED")
