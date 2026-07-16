# Auto-G16 Research Output Citation Template

Copy this block into the provenance section of future papers, supporting
information packages, and released research datasets. Replace every angle-
bracketed field; do not infer or silently omit unavailable values.

```text
Auto-G16 version: <X.Y.Z>
Auto-G16 version DOI: <10.5281/zenodo...>
Auto-G16 Git commit: <full commit SHA>
Auto-G16 release manifest: <release-manifests/vX.Y.Z.json>
Auto-G16 release-manifest SHA-256: <SHA-256>
Software Heritage SWHID: <swh:1:rev:... or explicitly pending>
Gaussian program and version: <reviewed value>
Scientific method/protocol record: <immutable identifier and SHA-256>
Study identifier: <stable study ID>
Calculation/candidate/job identifiers: <stable identifiers>
Gaussian input SHA-256 values: <one full SHA-256 per material input>
Workflow-manifest SHA-256 values: <one full SHA-256 per material manifest>
Evidence access classification: <public/private/restricted and basis>
Evidence package publication date: <ISO-8601 date>
```

Suggested prose citation:

```text
The workflow was prepared and audited with Auto-G16 v<X.Y.Z>
(version DOI <DOI>; Git commit <SHA>). Exact Gaussian input and workflow
manifest SHA-256 values are reported in the accompanying provenance table.
```

This record supplements, and does not replace, citation of Gaussian, the
scientific method, primary literature, and any separately released dataset.
