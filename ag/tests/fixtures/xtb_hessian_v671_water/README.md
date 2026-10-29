# xTB 6.7.1 real nonresearch water format sample

This is a sanitized copy of one actual gas-phase, closed-shell GFN2-xTB water
`--ohess tight` execution on 2026-10-29, independently reviewed for format,
geometry frame, effective masses, scale, signed spectrum and Cartesian modes.
It is not synthetic, and the importer never executes its captured command.
The original run remains private and unchanged. Public-copy sensitivity/data review passed independently on 2026-10-29;
source byte bindings, the two stdout redactions, and all six unchanged numeric
files were checked against the private originals.

Build: conda-forge osx-64 `6.7.1 gfortran_h7141999_5`, banner revision `edcfbbe`.
The recipe includes 1072/1133/1278/1374/version patches; this is not described as
an unmodified upstream binary. The audited numerical paths match upstream
commit `26b28010e805f7d1aeeef39813feb473e69cc4be`.

`hessian`, `g98.out`, `water.xyz`, `xtbopt.xyz`, `vibspectrum`, and `stderr.txt`
retain original numeric/file bytes. The compiled-by identity and executable
path in stdout are redacted. Execution/package/result JSON files have local
paths redacted; result hashes/sizes are rebound to these sanitized bytes.
`provenance.json` explicitly maps original SHA-256 to fixture SHA-256 and lists
each transformation. It does not claim that redacted logs equal original bytes.
`source.json` is the import declaration for these actual fixture bytes.

Hessian: 9×9 unweighted Eh/bohr², axis order x1,y1,z1,...; F15.10, row chunks
5+4, six Cartesian rigid directions already projected. Geometry: the original
g98 standard orientation, angstrom, F12.6; do not substitute the input XYZ.
Effective masses: O/H/H = 15.99940492/1.00794075/1.00794075 u; Hessian scale 1.
The three reconstructed internal wavenumbers are approximately
1538.898353342254, 3642.665506794502, 3651.164333474144 cm^-1.
All nine signed values are retained; external rounding values span roughly
-0.031 to +0.045 cm^-1. g98's displayed vectors are mass weighted, not the
Cartesian displacements used by G0.

`xtbopt.xyz` uses mctc-lib 0.5.2's 0.5291772109044924 angstrom/bohr;
g98 uses 0.52917726. Their small difference is accounted for by those writer
constants and the six-decimal print interval, without replacing either file.
This sample validates this build and ordinary nonlinear water path only.
It does not validate isotope overrides, linear/frozen/biased/periodic paths,
other builds, chemical identity mappings, or scientific stationary-point claims.

The local `.gitattributes` exempts only the four raw writer files' actual
trailing padding (and stdout's final blank line) from whitespace diagnostics.
Removing that padding would change the reviewed bytes and Hessian writer format.
