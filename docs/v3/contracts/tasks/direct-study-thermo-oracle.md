# Auto-G16 independent butane thermochemistry acceptance

Status: calculate-only contract frozen after independent review on 2026-10-12,
within BUTANE-RELIABILITY-UNIFIED-E2E-01. Comparison/population adapters below
remain explicitly unfrozen and do not issue acceptance.
This is an acceptance oracle, never the primary thermochemistry owner or a
replacement for native frequency eligibility and immutable result saving.

## Closed scientific scope

Version the existing independently exercised partition-function implementation
as `auto_g16.study._thermo_oracle`. Its numerical implementation imports only
Python standard-library modules, not Auto-G16's primary thermochemistry,
GoodVibes, NumPy or SciPy. It independently parses the original newly captured
Gaussian frequency-log bytes. No saved thermochemistry number is used as an
input to that calculation. The Study scientific adapter must separately prove
the exact accepted native Freq source, geometry/member and content digest;
passing the oracle alone grants no native eligibility or scientific acceptance.

The function is `calculate(raw_log: bytes)` and has no file access, saving,
subprocess, network, state mutation or configuration discovery. Exactly one
bounded log (maximum 64 MiB) is accepted per call. The supported finite scope
is the already selected neutral closed-shell butane Freq at 298.15 K, 1 atm,
scale 1; require charge 0, multiplicity 1, 14 atoms, precisely indexed modes
1–36 with positive frequencies, one SCF energy, one normal Gaussian termination,
no error termination, one molecular mass, one rotational symmetry number,
three positive rotational temperatures, one thermochemistry condition block
matching 298.15 K/1 atm and the complete reported thermochemistry table.
Locate that table by its unique E (Thermal)/CV/S header and exact KCal/Mol,
Cal/Mol-Kelvin, Cal/Mol-Kelvin units; read the five ordered rows immediately
after it. Gaussian also prints Electronic/Translational/Rotational rows in a
separate Q/Log10(Q)/Ln(Q) table; those are not thermochemistry duplicates.
Reject duplicate, missing, nonfinite or malformed singleton values and
combined jobs rather than selecting the last match. Count singleton candidates by
label before validating the entire record, including its exact permitted suffix;
a malformed duplicate must not disappear from the count. The separately
formatted population-analysis `Charge=<number> electrons` scalar is not the
charge/multiplicity record and is excluded only after a full-line format match. Atom-count records allow
only a bare NAtoms value or the two Gaussian NQM/NQMF/NMMI/NMMIF and
NActive/NUniq/SFac/NAtFMM/NAOKFM/Big metadata forms. Frequencies, mass and
rotational temperatures must be positive; sigma is an integer from 1 to 100.
Electronic energy may be negative, and free-energy corrections may have either
sign. Repeated Gaussian NAtoms reports are allowed only when every report is
14 (one to eight reports); this is not a duplicated thermochemistry block.
Do not infer a conformer
label or rotational symmetry number. Method/basis and connectivity are still
validated by the native accepted source and independent geometry review.

Use a newly constructed local Decimal context of 50 digits, ROUND_HALF_EVEN,
Emin=-999999, Emax=999999, clamp=0, with InvalidOperation, DivisionByZero and
Overflow traps; never inherit caller rounding/traps or modify global precision.
Raw numeric tokens are bounded to 64 characters and, except zero where allowed,
adjusted decimal exponents from -12 through 12. Larger tokens reject as outside
this finite butane parser's numerical bounds. Translation uses the fixed number density P/(R*T)*N_A during
temperature differentiation; include the Stirling entropy term. Rotation uses
the actual reported symmetry and rotational temperatures for a nonlinear
molecule. Harmonic oscillators include ZPE. Evaluate partition functions at
T±h and T±2h, with h=0.01 K, for five-point numerical derivatives; repeat with
h/2 and report the maximum energy and entropy changes separately with their
units. Residuals cover translation, rotation and every mode's HO, free-rotor and
Head-Gordon partition functions, not just the HO modes. Do not compare or
maximize J/mol and J/mol/K as one physical residual.
No closed-form primary energy or
entropy kernel is called. Electronic entropy is zero only after the explicit
closed-shell multiplicity check.

The constant convention is exactly the reviewed GoodVibes 4.3.0 comparison:
R=8.3144621 J mol^-1 K^-1, k=1.3806488e-23 J K^-1,
h=6.62606957e-34 J s, c=29979245800 cm s^-1,
N_A=6.0221415e23 mol^-1, atomic mass unit=1.66053886e-27 kg,
pi=3.1415926535897932384626433832795028841971693993751,
Hartree→J/mol=4.184*627.509541*1000. These intentionally frozen constants are
not represented as a new SI recommendation. Keep the explicit numerical
difference between R/k and N_A in the Head-Gordon ZPE convention; report its
residual and the coherent-constant countercheck rather than silently correcting
the primary implementation's chosen convention.

qRRHO uses the already reviewed Grimme entropy interpolation and Head-Gordon
enthalpy correction, cutoff 100 cm^-1 for both, interpolation exponent 4,
Bav=1e-44 kg m^2, frequency and ZPE scale 1. Preserve the existing independent
partition implementation's free-rotor inertia and derivative treatment. Report
each of 36 modes' frequency, weight, ZPE, HO/free-rotor entropy, corrected U/S,
delta H/S/G and Head-Gordon constant residual. Also report translational,
rotational, vibrational and pV contributions, total RRHO/qRRHO H/S/G, the
Gaussian printed corrections/table and the step-halving residual.

## Result and comparison

Return a detached closed mapping `auto-g16-independent-thermo-oracle/1`:
{schema,source_sha256,conditions,constants,parsed,components,modes,results,
reported,numerical_check}. Numerical values are finite canonical decimal strings
to preserve independent precision; IDs/mode counts and sigma remain integers.
The exact nested field inventory is defined below, based on the retained
independent-partition.py with separately dimensioned derivative residuals.
It must not admit arbitrary extra result fields.

A separate pure `compare_pair` adapter will consume the native saved pair's
closed public projection and two oracle outputs only after exact member/source
hash matching. It is a separate reviewed surface, not implicit in calculate.
Acceptance tolerances remain the previous checked values: total energies
1e-10 Hartree, contributions 1e-5 J/mol, entropy 1e-7 J/mol/K; printed Gaussian
values have 1e-6 Hartree and 0.0015 cal/mol/K rounding tolerances. Independent
Boltzmann calculations must use degeneracies anti=1, one gauche representative=2
without another symmetry/degeneracy multiplication. The population comparison
adapter and exact report schema must be frozen before it can issue acceptance.

## Evidence

Test malformed/duplicate blocks, wrong charge/multiplicity, atom/mode counts,
imaginary/zero modes, wrong conditions, nonfinite numbers and multi-job logs.
Test global Decimal context remains unchanged and that the oracle imports no
primary numerical owner. Compare analytic translation/rotation limits and
step-halving convergence; do not test merely against copied saved totals.
Then run this new implementation against the retained real logs and compare
its output with the independently retained source calculations as a regression,
explicitly historical evidence. Final acceptance reruns it against the new
study's actual logs. No raw Gaussian output or private runtime path enters Git.

## Exact calculate result fields

All object keys below are closed. Decimal serialization uses fixed-point decimal
notation with no exponent, removes redundant trailing fractional zeroes and
the trailing decimal point, and maps either signed zero to `0`. Conditions is
{temperature_k,pressure_atm,frequency_scale,zpe_scale,entropy_model,enthalpy_model,
cutoff_cm1,alpha,bav_kg_m2}; the two model values are grimme/head_gordon and all
others the fixed numeric strings above. Constants is
{gas_constant_j_mol_k,boltzmann_j_k,planck_j_s,speed_of_light_cm_s,avogadro_mol,
atomic_mass_kg,pi,hartree_j_mol,convention}; convention is
`goodvibes-4.3.0-frozen-comparison`. Parsed is
{electronic_energy_hartree,molecular_mass_amu,rotational_symmetry_number,
rotational_temperatures_k,frequencies_cm1,charge,multiplicity,atom_count}; sigma,
charge, multiplicity and atom_count are integers; temperatures/frequencies are
arrays of exactly 3/36 numeric strings.

Components has exactly E_electronic_Eh,ZPE_J_mol,U_trans_J_mol,U_rot_J_mol,
U_vib_RRHO_J_mol,U_vib_thermal_RRHO_J_mol,U_vib_qRRHO_J_mol,pV_J_mol,
S_trans_J_mol_K,S_rot_J_mol_K,S_elec_J_mol_K,S_vib_RRHO_J_mol_K,
S_vib_qRRHO_J_mol_K,Hcorr_RRHO_J_mol,S_RRHO_J_mol_K,Gcorr_RRHO_J_mol,
Hcorr_qRRHO_J_mol,S_qRRHO_J_mol_K,Gcorr_qRRHO_J_mol,
delta_H_q_minus_R_J_mol,delta_S_q_minus_R_J_mol_K,delta_G_q_minus_R_J_mol.
Modes has exactly 36 rows with keys mode,frequency_cm1,weight_HO,ZPE_J_mol,
U_HO_J_mol,U_q_J_mol,S_HO_J_mol_K,S_free_rotor_J_mol_K,S_q_J_mol_K,
delta_H_J_mol,delta_S_J_mol_K,delta_G_J_mol,HG_constant_residual_J_mol;
mode is integer 1–36. No caller conformer label is inferred or included.
Results is {RRHO,qRRHO}, each exactly {H_Eh,S_J_mol_K,G_Eh}.
Reported is {ZPE_Eh,Ucorr_Eh,Hcorr_Eh,Gcorr_Eh,Total,Electronic,Translational,
Rotational,Vibrational}; the five table rows each contain
{U_kcal_mol,Cv_cal_mol_K,S_cal_mol_K}. Numerical_check is
{decimal_digits,derivative_step_k,energy_residual_J_mol,entropy_residual_J_mol_K,
HG_constant_residual_J_mol,qRRHO_G_coherent_constants_Eh}; decimal_digits=50
is an integer, other values are numeric strings.
