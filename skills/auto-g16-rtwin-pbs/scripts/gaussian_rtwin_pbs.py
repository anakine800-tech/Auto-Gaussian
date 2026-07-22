#!/usr/bin/env python3
"""Compatibility entry point for the Auto-G16 legacy RTwin/PBS backend.

The implementation source exists only in ``legacy_rtwin_pbs.py``. Loading it
into this compatibility namespace preserves historical monkeypatch/import
semantics; executable dispatch still crosses ``execution_facade``.
"""

from __future__ import annotations

from pathlib import Path as _WrapperPath


_wrapper_name = __name__
_backend_path = _WrapperPath(__file__).with_name("legacy_rtwin_pbs.py")
_backend_source = _backend_path.read_bytes()
globals()["__name__"] = "_auto_g16_legacy_rtwin_pbs_implementation"
try:
    exec(compile(_backend_source, str(_backend_path), "exec"), globals(), globals())
finally:
    globals()["__name__"] = _wrapper_name
    del _backend_source


def main(argv: list[str] | None = None) -> int:
    from execution_facade import main as facade_main

    return facade_main(argv=argv)


if _wrapper_name == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
