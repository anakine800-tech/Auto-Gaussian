# Test-only backend fixture checkout

The native HTTP integration test accepts `AUTOG_TEST_BACKEND_CHECKOUT` as an
absolute backend source checkout root. In the joint repository, CI sets it
to the repository root while running frontend tests from `frontend/`.
The checkout must be the exact source used to build the installed backend wheel.

The variable is read only by `tests/backend_fixture_source.py`; it is not a
product setting, registration input, CLI option or HTTP parameter. It neither
installs nor executes a backend and must not be added to a deployed launcher.
An explicitly empty, relative, missing or incorrect path fails rather than
falling back. Without an override, the existing frontend `.ci/backend` lookup
and source-package fallback remain supported.

Before fixture import, the test compares installed `auto_g16` owner bytes with
the checkout for `query/native.py`, `conformer/thermochemistry_readonly.py`,
`conformer/frequency_readonly.py` and `thermochemistry/_native_service.py`.
Fixture modules and the scripts directory must exist. This preserves the
existing four-owner identity check; it is not a full checkout authenticity or
all-package equivalence check. CI/build source identities remain separately
bound to the reviewed commit/tree and wheel.

Only the `tests` and `scripts` package namespaces are extended for synthetic
fixtures. The backend checkout root is never inserted in `sys.path`, so it
cannot replace the already installed `auto_g16` package. Run installed-package
validation without a backend PYTHONPATH, and verify both product imports resolve
to the installed wheels before loading the frontend test modules.

The helper tests cover the nested frontend layout, explicit-path precedence,
legacy fallback, invalid overrides without fallback, missing fixtures/owners,
each checked owner mismatch, and unchanged `sys.path`. The existing real native
HTTP integration test must also run using actual installed backend/frontend
wheels and the explicit source checkout. Fixtures use disposable stores and
fake scientific kernels, not operational calculation data.

The root joint workflow uses this test-only input. Public study interfaces and
deployment remain separate acceptance requirements; the fixture override does
not configure product runtime.
