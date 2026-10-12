# Saved native thermodynamics (read only)

This page implements NATIVE-THERMO-ADAPTATION-04 contract r1, SHA256
`468275ff3ae413b745d2a40ee51c3a11f418104ab59b82c2cb4ac6e88a36ad45`.
It projects an already saved, source-bound pair. It neither computes thermochemistry
nor grants scientific acceptance. The existing Gaussian original report is retained.

## Startup registration

`autog-native-source-registration/4` has exactly `schema` and `sources`. Each source
has exactly `source_id`, `database`, `snapshots`, `opt_readout`, `freq_readout`, and
`thermodynamic_readout`. The first five fields retain their /3 semantics and bounds.
The new field is `null` or exactly `{"path": "<absolute registration path>",
"sha256": "<64 lowercase hex characters>"}`. This is trusted startup configuration,
never an HTTP input. /1, /2 and /3 keep their existing closed field sets.

The descriptor is read with the existing pinned, no-follow reader, capped at 1 MiB,
then passed to `load_native_thermodynamic_readout`. Startup performs registration
validation only; it does not read the saved results. The backend `NativeSource`
validator owns exact reader type, full frequency readout equality, database,
unique snapshot/Attempt and parsed revision associations. A thermodynamic reader
cannot be moved to a different source identity by changing a page route.

A matching fourth-package backend with `NativeSource.thermodynamic_readout` and
`NativeQueryService.get_thermodynamics` is required. Existing installed backends
are not implicitly upgraded. Package versions and installation locks are unchanged.

## HTTP and page contract

The only new route is
`GET /api/v1/native/sources/{source_id}/attempts/{attempt_id}/thermodynamics`.
It uses the existing authorization, origin, method, query/body rejection, response
byte cap and safe error envelope. The owning query returns exactly
`{schema, kind, data}` with schema `auto-g16-native-thermodynamics-query/1` and kind
`thermodynamics`. Existing native query schemas and list/detail DTOs are unchanged.

The page requests this resource once after the visible Attempt detail has loaded.
Lists never request it. Route or token changes discard old results. It uses the
existing `native-scientific-read` policy: 120-second deadline, two requests for the
whole page, and no automatic retry. Loading, unregistered, failed and available
states are distinct; failure preserves the completed original detail.

The decoder rejects missing/extra fields throughout the projection, invalid
identities/digests/numbers, unsupported policy values, cross-source or cross-Attempt
responses, duplicate member associations and inconsistent selected-member markers.
Rejected responses show `contract-mismatch`; no partial successful table is shown.
The page preserves member order and JavaScript's round-trip numeric representation.
It does not round to presentation precision, convert units, calculate relative
energies or re-normalize populations. Energies use Hartree, entropy Hartree/K,
temperature K, cutoff cm⁻¹, and populations are dimensionless.

Only whitelisted source identities and hashes are displayed. No private provenance,
paths or raw logs are accepted in the new DTO. Parameters are read only. The page
makes no exhaustive-sampling, global-minimum or scientific-acceptance claim.

## Validation and release boundary

Focused tests: `tests.test_native_sources`, `tests.test_native_http`; build/typecheck:
`pnpm --dir web build`; synthetic browser suite:
`pnpm --dir web test native-thermodynamics.spec.ts native-frequency.spec.ts native-navigation.spec.ts`.
The real registry-to-HTTP integration test reuses the pinned backend's disposable
synthetic fixture and fake kernels. All reads run with real computation forbidden.
CI pins backend `afffc8c578fa541c8af1d9af39e861146e399b4d`
at `.ci/backend`; for local focused tests, put the
matching backend source checkout on `PYTHONPATH`. The test compares imported owner
bytes with the fixture checkout and fails if the fixture or matching owner is absent.
It checks exact saved values, source/Attempt selection, one read without nested
Freq reads, zero added reads on old routes, and preservation of the original detail.
The synthetic UI server creates its own fixture stores and does not read real data.

Cross-repository acceptance must name the exact final fourth-package backend commit,
frontend commit and dependency versions. The Owner's 2026-10-09 CI scope addendum
allows `.github/workflows/frontend-offline.yml` to replace its four backend SHA
occurrences with the same reviewed, published fourth-package commit and append
`native-thermodynamics.spec.ts` to the existing browser selector. All other workflow
content is preserved. Installation, real source registration, real browser acceptance,
merging, new calculations and cleanup are separate operations outside this implementation.
