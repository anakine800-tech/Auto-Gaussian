# Auto-G16 local pinned Draft 2020-12 validation

`scripts/run_schema_validation.py` is the reviewed, offline-only local entry
for real Draft 2020-12 contract tests. It does not create a virtual environment,
run an installer, contact a package index, or modify the `core` or `chem`
profiles. Environment preparation is a separate user-owned action.

## Use an existing isolated environment

Pass either the environment root or its exact Python executable:

```bash
./scripts/python core scripts/run_schema_validation.py \
  --env /absolute/path/to/schema-validation-venv

./scripts/python core scripts/run_schema_validation.py \
  --python /absolute/path/to/schema-validation-venv/bin/python
```

`AUTO_G16_SCHEMA_VALIDATION_PYTHON` is the equivalent explicit environment
variable for one absolute `bin/python` or `Scripts/python.exe` path. Repeated
`--env` or `--python` arguments form a local compatibility matrix; every
candidate is validated before any test starts, and every validated candidate
must pass.

With no explicit candidate, the runner checks only these conventional existing
locations; it never scans the home directory or creates a missing path:

- `.venv-schema-validation` at the repository root;
- `/private/tmp/auto-g16-jsonschema-review/venv311`;
- `/private/tmp/auto-g16-jsonschema-review/venv312`;
- `/private/tmp/auto-g16-jsonschema-review/venv313`.

The repository-local directory is ignored by Git. A conventional environment
must be a real directory with exactly one `bin/python` or
`Scripts/python.exe` and exactly one non-symlink env-local
`lib/python*/site-packages` or `Lib/site-packages`. The Python executable may
be the normal virtual-environment link to a base interpreter: the test-only
package layer, not a copy of the interpreter binary, is the isolated resource.
On POSIX, the environment directory chain must be owned by the current user
and must not be group- or other-writable; the resolved interpreter must also
be owned by that user. An unsafe candidate blocks before its interpreter
executes. This is required for the conventional `/private/tmp` discovery
locations.

## Fail-closed gate

Before tests, the runner:

1. reads the public Schema-validation lock and the ordered module command from
   the versioned CI workflow;
2. invokes each candidate with Python isolated/no-site mode (`-I -S`), a
   minimal environment, and only its explicit env-local `site-packages` path;
3. reads only the Python version and package versions named by the lock;
4. requires the exact six locked package versions, including
   `jsonschema==4.26.0`, and a Python minor in the public supported range from
   `pyproject.toml`;
5. runs the CI-owned ordered inventory with
   `AUTO_G16_REQUIRE_JSONSCHEMA=1`, user-site disabled, bytecode writes
   disabled, and no global/user site, `.pth` processing, `HOME`, `PYTHONPATH`,
   runtime-profile, transport, or private configuration variable forwarded.

The CI workflow remains the sole owner of the ordered current inventory; the
local runner does not copy the 17 module names. The static Python contract
audit verifies that every discovered `test_*schema_draft202012.py` file agrees
with that CI inventory and that the local runner remains under progressive
static quality.

Exit status and terminal wording are part of the developer contract:

- `0` and `PASS` only after the real canonical unittest command exits zero in
  every validated environment;
- `1` and `FAIL` when the canonical tests run but fail;
- `2` and `BLOCKED` when no candidate exists, a path is not isolated, a package
  is missing or drifted, the lock/CI contract is invalid, or the probe is not a
  closed valid document.

`BLOCKED` includes the exact candidate and mismatch plus an actionable
`--env`/`--python` command. It must not be rewritten as PASS, and an ordinary
core-suite skip must not substitute for this entrypoint.
