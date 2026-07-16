# Auto-G16 Release Provenance and Citation Policy

This policy applies to public Auto-G16 releases after `v2.3.0`. It records
authorship and exact released content; it does not grant scientific acceptance,
calculation authority, patent rights, or permission to publish private research.

## Release identity chain

Every release after `v2.3.0` must bind this chain:

```text
reviewed commit -> signed annotated tag -> GitHub Release
                -> release manifest -> Zenodo version DOI
                -> Zenodo concept DOI -> Software Heritage SWHID
```

- The annotated tag must carry an SSH or OpenPGP signature. Existing tags
  through `v2.3.0` are immutable historical baselines and are not rewritten.
- The release manifest binds the tag object ID, peeled commit SHA, release
  timestamp, an immutable versioned `CITATION.cff` snapshot, optional release
  artifacts, DOI values, and SWHID.
- A DOI or SWHID may initially be `null`. The identifier update command may
  fill an empty field, but refuses to replace a different non-null identifier.
- A DOI is an archival identifier, not a copyright registration or patent.

The `v2.3.0` manifest is explicitly marked `post_release_backfill`: its tag and
GitHub Release predate this policy, and its versioned citation snapshot was not
part of the original tag. Every later manifest is `release_native`, and its
versioned citation snapshot must be committed before the signed release tag.

## Release procedure

1. Complete the normal release checklist, tests, security scan, review, and
   explicit publication approval.
2. Before tagging, copy the reviewed root `CITATION.cff` to
   `release-manifests/citations/vX.Y.Z.cff`. This versioned snapshot is
   immutable even when the root citation file advances to a later release.
3. Create a signed annotated tag. Do not rewrite or re-sign an existing tag.
4. Publish the GitHub Release and allow the connected Zenodo repository to
   archive it.
5. Generate the manifest, initially leaving identifiers empty when necessary:

   ```bash
   ./scripts/python core scripts/release_provenance.py generate \
     --tag vX.Y.Z \
     --published-at YYYY-MM-DDTHH:MM:SSZ \
     --release-url https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/vX.Y.Z \
     --output release-manifests/vX.Y.Z.json
   ```

6. Record both Zenodo identifiers. Use the version DOI for exact reproducibility
   and the concept DOI for the evolving Auto-G16 project.
7. Request or confirm Software Heritage archival and record the revision SWHID.
   The repository snapshot returned by Save Code Now is useful request evidence,
   but a release manifest records the `swh:1:rev:` identifier for the exact
   release commit.
8. Fill the identifiers in the manifest and README without changing any
   already-recorded identifier:

   ```bash
   ./scripts/python core scripts/release_provenance.py update-identifiers \
     --manifest release-manifests/vX.Y.Z.json \
     --version-doi 10.5281/zenodo.VERSION_RECORD \
     --concept-doi 10.5281/zenodo.CONCEPT_RECORD \
     --swhid swh:1:rev:REVISION_HASH \
     --readme README.md
   ```

9. Validate locally and in CI:

   ```bash
   ./scripts/python core scripts/release_provenance.py validate \
     --manifest release-manifests/vX.Y.Z.json
   ```

DOI/SWHID backfill is a reviewed follow-up commit. It does not alter the
released tag, source archive, or historical release date.

## Signing keys

Use a dedicated signing key when practicable; never commit a private key.
Register only the public signing key with GitHub. GitHub's `Verified` badge is
reviewed after publication, but the offline manifest records only whether the
annotated tag contains an SSH or OpenPGP signature. Cryptographic verification
and key-identity review remain separate release evidence.

## Research-output minimum record

Every future paper, supporting information package, public research dataset,
and calculation evidence package that used Auto-G16 must record:

- exact Auto-G16 version and version DOI;
- exact Git commit SHA;
- SHA-256 of every material Gaussian input and reviewed workflow manifest;
- applicable study, calculation, candidate, protocol, and job identifiers;
- the Gaussian program/version and independently reviewed scientific method;
- the date and public/private access classification of the evidence package.

The repository concept DOI alone is not sufficient for reproducing a concrete
study. A Git branch name, `latest`, screenshot, or mutable URL is not an exact
software identity.
