# Auto-Gaussian Frontend

Local frontend over the Auto-Gaussian query contracts. The reviewed native readout entry is read-only; optional legacy library/monitor/task features require their own explicit configuration and authority.

## Source and dependency baseline

The proposed publication baseline is a sanitized snapshot of frontend `77c6b45ef13d14824ce176603f3daedf1f5c15e4`. Native query, Opt/Freq registration and transport deadline changes come from `1acbdcaa1bd5dec01ffad41d1bf80deaffe1eb3a` (tree `89274fb31da6a1b298734a79e1615c62a87e4a91`). This is a new publication history; original local history remains unchanged and is not uploaded. No claim that the new publication commit equals the original source commit.

Backend qualification is bound to `anakine800-tech/Auto-Gaussian` commit `e0d239e41529649e25610eef6312d69714cf44e5`. The distribution name/version `auto-g16==2.7.0` alone is insufficient to identify these query and Freq capabilities; CI checks out the exact backend commit. Runtime package version remains unchanged; use commit/tree and wheel hashes for artifact identity.

Three historical operational acceptance scripts are excluded from publication because they contain machine-specific paths or execution identities. Other `web/scripts/accept-*` and real-data utilities remain manual operational tools, outside default CI. Their presence is not permission to run them. The old `scripts/prepare_result_dependency.py` also requires an external historical dependency manifest and is not the standard build or CI entry.

## Offline validation

CI uses disposable synthetic stores only, Python 3.13.13, Node 24.19.0, the exact Python versions in `requirements.lock.txt`, pnpm 11.19.0 and `web/pnpm-lock.yaml`. It runs the Python suite, TypeScript/build, five transport deadline cases and affected synthetic native/navigation browser tests. It does not invoke real-data acceptance scripts, SSH, PBS, Gaussian, deployment or mutation of production data. Public package registries supply third-party dependencies in CI; remote provisioning and CI success require validation on the new repository, and are not established by the local results.

The sanitized commit/tree and file-hash source map is published in `docs/publication-source-map.json`. Private local installation and UI evidence remain in the local review packet. No SQLite databases, source-registration paths, job receipts, raw computational output, checkpoints, private host configuration or installed launchers belong in this source repository.

## Native read semantics and current scope

Native scientific reads use a 120-second transport deadline after acquiring one of the two page-level slots. Ordinary requests retain 15 seconds. Navigation abandons only the consumer; the in-flight slot remains until settlement/deadline, stale route results are isolated, errors remain errors, and no automatic retry is added. The client deadline does not prove server-side work stopped.

Opt/Freq mode counts, units, parser provenance and ensemble revision are evidence display. Machine `validated_minimum` is not a human ScientificAcceptance, a thermodynamic eligibility decision, or authority to run a new job. CI success, source merge and installation authorization are separate decisions.
