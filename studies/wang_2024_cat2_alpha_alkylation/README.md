# Wang 2024 CAT2 alpha-alkylation real offline forward study

This package records a real chiral-bisborane reaction from JACS 2024, DOI
`10.1021/jacs.4c09067`, without converting incomplete literature evidence into a
runnable calculation study.

The reported reaction identity, conditions, product assignment, yield, and ee
are evidence-backed. The complete CAT2 active state, atom inventory, charge,
multiplicity, Cartesian coordinates, atom map, stereochemical channel mapping,
selectivity-determining step, common reference basin, and computational protocol
are not established by the available evidence. Consequently:

- `forward-study.json` remains `calculation_ready: false` and
  `no_submission_authorization: true`;
- it is deliberately not emitted as
  `gaussian-asymmetric-catalysis-study/1`, because satisfying that contract now
  would require inventing scientific fields;
- no candidate, materialization specification, Gaussian input, or server plan
  exists in this directory; and
- the published BF3 geometries are linked only as an achiral mechanistic
  submodel. They are not CAT2 geometries and are not an ee ensemble.

The candidate-space section is a review matrix. Empty levels are blocking
evidence, not missing implementation work. Once reviewers supply the active
state, complete structures and atom maps, explicit channel mapping, and an
approved protocol, a new formal study can be built with `build-study` and
`enumerate-boron`.

Run the offline checks with:

```bash
python3 -m unittest tests.test_asymmetric_real_case
```

No file in this package authorizes Gaussian, SSH, PBS, deployment, cancellation,
or creation of a server directory.
