# Auto-G16 local pinned Draft 2020-12 validation

`scripts/run_schema_validation.py` is the reviewed, offline-only local entry
for real Draft 2020-12 contract tests. It does not create a virtual environment,
run an installer, contact a package index, or modify the `core` or `chem`
profiles. Environment preparation is a separate user-owned action.

## Use an existing package overlay

Pass only the environment root:

```bash
./scripts/python core scripts/run_schema_validation.py \
  --env /absolute/path/to/schema-validation-venv
```

`AUTO_G16_SCHEMA_VALIDATION_ENV` is the equivalent explicit environment
variable for one absolute environment root. Repeated `--env` arguments form a
local compatibility matrix; every candidate is validated before any test
starts, and every validated candidate must pass. There is deliberately no
`--python` option: `bin/python`, `Scripts/python.exe`, shell shims, and every
other environment-local executable are ignored and never run.

With no explicit candidate, the runner checks only these conventional existing
locations; it never scans the home directory or creates a missing path:

- `.venv-schema-validation` at the repository root;
- `/private/tmp/auto-g16-jsonschema-review/venv311`;
- `/private/tmp/auto-g16-jsonschema-review/venv312`;
- `/private/tmp/auto-g16-jsonschema-review/venv313`.

The repository-local directory is ignored by Git. A conventional environment
must contain exactly one non-symlink
`lib/python<current-major.minor>/site-packages`; any other ABI/minor directory
blocks. The package overlay, not an environment interpreter, is the only
candidate resource. On POSIX, its directory chain must be owned by the current
user and must not be group- or other-writable. The runner opens both the
environment root and the unique `site-packages` no-follow and retains both
directory descriptors across probe and test execution, so a later path
replacement cannot silently select a new overlay.

## Fail-closed gate

Before tests, the runner:

1. reads the public Schema-validation lock and the ordered module command from
   the versioned CI workflow;
2. uses only the Python that is already executing the runner (`sys.executable`)
   for every child process; candidate programs are never invoked;
3. invokes that trusted Python in isolated/no-site mode (`-I -S`) with a
   minimal environment, changes directory through the retained package-overlay
   descriptor, and does not use `PYTHONPATH`, `.pth`, `sitecustomize`, or a
   reopened candidate path;
4. requires the exact six locked package versions, including
   `jsonschema==4.26.0`, and a Python minor in the public supported range from
   `pyproject.toml`; the overlay path must encode that same Python minor;
5. verifies that every locked distribution has a non-empty file inventory,
   every listed file is regular and descriptor-relative with no symlink or
   root escape, every primary import origin is one of those files, and every
   ordinary `site-packages` RECORD entry matches its declared SHA-256 and
   size. Exactly one unhashed self-entry for that distribution's own RECORD is
   required. The only other unhashed internal entry permitted is an exact
   current-interpreter `__pycache__/<source>.<cache-tag>.pyc` whose matching
   `.py` source is a hashed entry in the same RECORD. Candidate bytecode is
   disabled as an import source through a trusted impossible bytecode-cache
   prefix, and every listed file still has a current SHA-256 manifest replayed
   immediately before and after tests. Partial hash/size declarations,
   unsupported unhashed files, duplicate paths, RECORD hash drift, and source
   tampering are `BLOCKED`.
   The only exception for a standard virtual environment is one non-import
   console script: its distribution must declare the exact `console_scripts`
   name, its RECORD path must normalize exactly to the same environment's
   `bin/<name>`, and its required RECORD SHA-256 and size, regular-file type,
   owner, mode, and inode must match through the retained environment-root
   descriptor. It is never executed. Any undeclared name, other escape,
   symlink, missing hash/size, or replacement is `BLOCKED`;
6. runs the CI-owned ordered inventory with
   `AUTO_G16_REQUIRE_JSONSCHEMA=1`, user-site disabled, bytecode writes
   disabled, and a closed exact child environment. `HOME` and
   `AUTO_G16_RUNTIME_CONFIG` are fixed to reviewed nonexistent `/proc` deny
   sentinels, while `LANG` and `LC_ALL` are fixed to `C`; caller values and all
   other runtime-profile, transport, private-configuration, and Python path
   variables are not forwarded. No global/user site or `.pth` processing is
   enabled.
   Before repository tests load, the child changes directory to the retained
   `site-packages` descriptor, inserts only `.`, limits distribution discovery
   to that path, imports and origin-checks all six packages, then restores the
   repository working directory through a separately identity-checked
   repository descriptor. The candidate path is not kept as an import path;
7. accepts success only when the trusted child returns both exit zero and a
   closed, non-empty unittest completion document over a separate inherited
   pipe. Missing, malformed, empty, or exit-disagreeing evidence is `BLOCKED`.

The CI workflow remains the sole owner of the ordered current inventory; the
local runner does not copy the 17 module names. The static Python contract
audit verifies that every discovered `test_*schema_draft202012.py` file agrees
with that CI inventory and that the local runner remains under progressive
static quality.

Exit status and terminal wording are part of the developer contract:

- `0` and `PASS` only after trusted Python reports real non-empty unittest
  completion and exits zero in every validated overlay;
- `1` and `FAIL` when the canonical tests run but fail;
- `2` and `BLOCKED` when no candidate exists, a path is not isolated, a package
  is missing or drifted, the lock/CI contract is invalid, or the probe is not a
  closed valid document, an import/distribution escapes the overlay, a file
  changes after probe, or trusted completion evidence is absent.

`BLOCKED` includes the exact candidate and mismatch plus an actionable
`--env` command. It must not be rewritten as PASS, and an ordinary core-suite
skip must not substitute for this entrypoint.
