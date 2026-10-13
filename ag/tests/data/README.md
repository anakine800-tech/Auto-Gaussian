# Synthetic geometry fixtures

`butane.xyz` contains explicit-hydrogen anti/gauche/gauche-prime test geometries.
They were generated locally with RDKit from `CCCC` (ETKDG seed 31, MMFF relaxation,
then setting the C-C-C-C torsion to 180, 60 and -60 degrees). The energies
(-157 and -156.999 Hartree) are invented test values, not calculation results.

The performance test in `test_dedup.py` generates 200 explicit-hydrogen C20
conformers in a temporary directory, with ETKDGv3 seed 20261013. All energies
are within the duplicate energy tolerance so all 19,900 pairs are compared.
The measured interval covers XYZ loading and deduplication, excluding synthetic
input generation. No generated ensemble is committed.
