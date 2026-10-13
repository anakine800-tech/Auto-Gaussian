# Auto-G16 V31 local program inventory

`scripts/qualify_v31_program.py` reads supplied local program bytes and xTB
runtime data. It creates no files and invokes no program. A successful result
means the local inventory completed; it does **not** prove production readiness,
a program's authenticity or supported behavior, a production ServerProfile,
remote installation, or live authority.

```bash
./scripts/python core scripts/qualify_v31_program.py \
  --kind xtb --path /absolute/local/xtb \
  --runtime-data /absolute/local/share/xtb
./scripts/python core scripts/qualify_v31_program.py \
  --kind crest --path /absolute/local/crest \
  --version-evidence /absolute/local/captured-version.json
```

The output is one JSON object on stdout. Exit 0 means
`LOCAL_CONTENT_INVENTORY_COMPLETE`; invalid, unavailable, or drifting evidence
exits 2 without a success object. Every output retains
`production_qualification: UNVERIFIED`, `program_executed: false`, and
`live_authority: false`. Without version evidence, `version` is null and
`version_verification` is `UNVERIFIED_PROBE_DEFERRED`.

Inputs must already use absolute canonical POSIX paths. All components are
opened descriptor-relatively with no-follow handling. Binary/data files must be
nonempty regular files; symlinks and special files are rejected. File identity,
size and change timestamps are checked before and after reading and again
before returning. Every visited runtime-data directory's complete name set and
identity are also rechecked, so additions/removals/replacements are not silently
omitted. This is a bounded observation, not an atomic filesystem snapshot or
protection against a malicious kernel or filesystem.

The limits are 1 GiB per binary/data file, 4 GiB total read bytes, 256 inventory
entries and 32 directory levels. The xTB manifest includes all regular files,
including nested extras, and uses the existing
`auto-g16-v31-xtb-runtime-data-manifest/1` validator and required eight-file
inventory. Output includes the exact canonical UTF-8 manifest (including its
terminal newline), SHA-256 and size for later review. The tool never installs
these bytes or binds them into a ServerProfile.

Optional captured version evidence uses this closed JSON shape:

```json
{
  "schema": "auto-g16-v31-captured-version-claim/1",
  "kind": "crest",
  "binary_identity": {
    "canonical_path": "/absolute/local/crest",
    "size_bytes": 123,
    "sha256": "<64 lowercase hexadecimal characters>"
  },
  "reported_version": "3.0.2",
  "captured_at": "2026-09-11T00:00:00Z",
  "stdout_base64": "<canonical base64 of captured UTF-8 output>",
  "stderr_base64": ""
}
```

The entire evidence file is capped at 64 KiB and each decoded stream at 32 KiB.
Duplicate keys, unknown fields, malformed encodings, a different binary
identity, or a reported version token absent from both streams reject. CREST
claims must report exactly `3.0.2`; suffixes or other versions reject. No xTB
version support policy is invented.

The timestamp, program kind, version and capture provenance are supplied claims.
Even when the binary hash and output token match, the tool returns
`UNVERIFIED_CAPTURED_CLAIM` and `capture_authenticity_verified: false`: hashing
the evidence binds its contents but cannot authenticate who captured it or prove
that this binary produced it. Output reports the evidence and stream hashes,
not a new trusted capture receipt. An independently approved production/version
probe and the remaining Owner gates are still required.

Focused synthetic validation:

```bash
./scripts/python core scripts/run_tests.py tests.v31.tooling.test_qualify_v31_program
```
