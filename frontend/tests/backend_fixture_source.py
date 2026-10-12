"""Test-only fixture discovery; never changes package imports or product settings."""
import hashlib
import os
from pathlib import Path


CHECKOUT_ENV = 'AUTOG_TEST_BACKEND_CHECKOUT'
OWNER_FILES = (
    'query/native.py', 'conformer/thermochemistry_readonly.py',
    'conformer/frequency_readonly.py', 'thermochemistry/_native_service.py',
)
FIXTURE_FILES = (
    'tests/v31/conformer/test_thermochemistry_readonly.py',
    'tests/v31/conformer/test_successor_freq.py',
)


def backend_fixture_checkout(frontend_root: Path, backend_package: Path) -> Path:
    """Resolve explicit checkout first; an invalid override must not fall back.

    In a monorepo the explicit checkout is the joint repository root, while
    frontend_root is its frontend/ child. backend_package is the already imported
    auto_g16 package, including site-packages when validating an installed wheel.
    """
    explicit = os.environ.get(CHECKOUT_ENV)
    if explicit is not None:
        checkout = Path(explicit)
        if not explicit or not checkout.is_absolute():
            raise RuntimeError(f'{CHECKOUT_ENV} must be an absolute backend checkout root')
    else:
        checkout = frontend_root / '.ci' / 'backend'
        if not checkout.is_dir():
            checkout = backend_package.parent
    try:
        checkout = checkout.resolve(strict=True)
        if (not checkout.is_dir() or not (checkout / 'scripts').is_dir()
                or not all((checkout / name).is_file() for name in FIXTURE_FILES)):
            raise RuntimeError('exact backend source checkout with synthetic fixtures is required')
        # Preserve the installed owner/source proof before any fixture import.
        for relative in OWNER_FILES:
            actual = hashlib.sha256((backend_package / relative).read_bytes()).digest()
            expected = hashlib.sha256((checkout / 'auto_g16' / relative).read_bytes()).digest()
            if actual != expected:
                raise RuntimeError('backend fixture/installed owner mismatch')
    except OSError as error:
        raise RuntimeError('exact backend source checkout with owner files is required') from error
    return checkout
